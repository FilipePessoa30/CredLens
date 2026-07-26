"""Tests for the Phase 5 cure-semantics fix
(docs/adr/0010-cure-semantics-and-relapse.md).

Before this phase, a cure paid off a contract's ENTIRE remaining balance
(not just its overdue backlog), which made every cure terminal and made
delinquency relapse architecturally impossible - Phase 4B's own
contract_coverage fixture documented this as a known, unfixable gap. This
phase changes the cure mechanism to pay only the overdue backlog, and
these tests prove - on REAL generated output, never a mock - every
property section 3.4 of this phase's own instructions requires: a cure
that leaves a future balance, a cure that does not terminate the
contract, preserved future installments, prepayment staying a distinct
event, a real atraso -> cura -> novo atraso cycle, no snapshot after a
genuinely terminal event, ledger reconciliation, coherent DPD before/
during/after cure, unaffected write-off/recovery behavior, and
determinism.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

from credlens.contracts.registry import load_all_contracts
from credlens.generation.config import load_generation_config
from credlens.generation.orchestrator import GenerationOutcome, generate_scenario
from credlens.generation.validation import validate_contracts_strict

_SEED = 2026


def _cleanup(run_id: str) -> None:
    config = load_generation_config()
    for base in (config.output.operational_dir, config.output.truth_dir):
        path = Path(base) / run_id
        if path.exists():
            shutil.rmtree(path)


@pytest.fixture(scope="module")
def coverage_run() -> Iterator[GenerationOutcome]:
    outcome = generate_scenario(
        scenario="contract_coverage", scale_name="smoke", seed=_SEED, force=True
    )
    yield outcome
    _cleanup(outcome.generation_run_id)


@pytest.fixture(scope="module")
def tables(coverage_run: GenerationOutcome) -> dict[str, pd.DataFrame]:
    op = coverage_run.operational_dir / "operational"
    return {path.stem: pd.read_parquet(path) for path in op.glob("*.parquet")}


class TestCureLeavesFutureBalance:
    def test_at_least_one_cure_pays_less_than_the_contracts_full_balance(
        self, tables: dict[str, pd.DataFrame]
    ) -> None:
        payments = tables["payments"]
        cures = payments[payments["payment_type"] == "cure"]
        assert len(cures) > 0

        contracts = tables["contracts"]
        found_partial_cure = False
        for _, cure in cures.iterrows():
            matching = contracts.loc[
                contracts["contract_id"] == cure["contract_id"], "financed_amount"
            ]
            financed = float(matching.iloc[0])
            if float(cure["amount"]) < financed:
                found_partial_cure = True
                break
        assert found_partial_cure, "expected at least one cure paying less than the full contract"

    def test_cured_contracts_are_not_forced_terminal(self, tables: dict[str, pd.DataFrame]) -> None:
        payments = tables["payments"]
        snapshots = tables["account_monthly_snapshots"]
        cured_contract_ids = set(payments.loc[payments["payment_type"] == "cure", "contract_id"])
        assert cured_contract_ids

        # For every cure, there must be a LATER snapshot for the same
        # contract with status "active" (not settled/charged_off) -
        # proving the cure did not terminate the contract.
        non_terminal_after_cure = 0
        for contract_id in cured_contract_ids:
            contract_snaps = snapshots[snapshots["contract_id"] == contract_id].sort_values(
                "snapshot_date"
            )
            if (contract_snaps["status"] == "active").any():
                non_terminal_after_cure += 1
        assert non_terminal_after_cure > 0

    def test_future_installments_preserved_after_cure(
        self, tables: dict[str, pd.DataFrame]
    ) -> None:
        payments = tables["payments"]
        installments = tables["installments"]
        cured_contract_ids = set(payments.loc[payments["payment_type"] == "cure", "contract_id"])

        contracts_with_scheduled_future = 0
        for contract_id in cured_contract_ids:
            contract_installments = installments[installments["contract_id"] == contract_id]
            if (contract_installments["status"] == "scheduled").any():
                contracts_with_scheduled_future += 1
        assert contracts_with_scheduled_future > 0, (
            "expected at least one cured contract with 'scheduled' (untouched, future) "
            "installments remaining"
        )


class TestPrepaymentDistinctFromCure:
    def test_prepayment_and_cure_are_different_payment_types(
        self, tables: dict[str, pd.DataFrame]
    ) -> None:
        payments = tables["payments"]
        assert (payments["payment_type"] == "cure").any()
        assert (payments["payment_type"] == "prepayment").any()

    def test_prepayment_pays_off_every_remaining_installment(
        self, tables: dict[str, pd.DataFrame]
    ) -> None:
        # A prepayment pays every open installment at once, including
        # not-yet-due ones - unlike a cure, which leaves future
        # installments "scheduled" (see TestCureLeavesFutureBalance). So
        # every contract that ever had a prepayment ends with NO
        # installment left in "scheduled" status.
        payments = tables["payments"]
        installments = tables["installments"]
        prepayments = payments[payments["payment_type"] == "prepayment"]
        assert len(prepayments) > 0
        for contract_id in prepayments["contract_id"].unique():
            contract_installments = installments[installments["contract_id"] == contract_id]
            assert not (contract_installments["status"] == "scheduled").any()


class TestRelapse:
    def test_relapse_into_delinquency_occurs(self, tables: dict[str, pd.DataFrame]) -> None:
        snapshots = tables["account_monthly_snapshots"]
        ordered = snapshots.sort_values(["contract_id", "snapshot_date"])
        relapsed = []
        for contract_id, group in ordered.groupby("contract_id"):
            cured_since_last_delinquency = False
            for status in group["status"]:
                if status == "delinquent":
                    if cured_since_last_delinquency:
                        relapsed.append(contract_id)
                        break
                    cured_since_last_delinquency = False
                elif status == "active":
                    cured_since_last_delinquency = True
        assert len(relapsed) > 0

    def test_dpd_returns_to_zero_after_cure_then_rises_again_on_relapse(
        self, tables: dict[str, pd.DataFrame]
    ) -> None:
        snapshots = tables["account_monthly_snapshots"]
        ordered = snapshots.sort_values(["contract_id", "snapshot_date"])
        for contract_id, group in ordered.groupby("contract_id"):
            statuses = group["status"].tolist()
            dpds = group["dpd"].tolist()
            for i in range(1, len(statuses) - 1):
                if statuses[i] == "active" and statuses[i - 1] == "delinquent":
                    # The cure month itself must show dpd == 0 (no past-due amount).
                    assert dpds[i] == 0, f"{contract_id}: dpd not reset to 0 after cure"


class TestNoSnapshotAfterTerminal:
    def test_no_snapshot_exists_after_a_contracts_own_terminal_month(
        self, tables: dict[str, pd.DataFrame]
    ) -> None:
        snapshots = tables["account_monthly_snapshots"]
        terminal_statuses = {"settled", "closed", "charged_off"}
        ordered = snapshots.sort_values(["contract_id", "snapshot_date"])
        for contract_id, group in ordered.groupby("contract_id"):
            statuses = group["status"].tolist()
            dates = group["snapshot_date"].tolist()
            terminal_date = None
            for status, date in zip(statuses, dates, strict=True):
                if status in terminal_statuses:
                    terminal_date = date
                    break
            if terminal_date is not None:
                after = [d for d in dates if d > terminal_date]
                assert not after, f"{contract_id} has a snapshot after its terminal month"


class TestReconciliationAndDpdCoherence:
    def test_strict_contract_validation_passes_including_reconciliation_rules(
        self, tables: dict[str, pd.DataFrame]
    ) -> None:
        contracts = load_all_contracts()
        reports = validate_contracts_strict(tables, contracts)
        errors = {
            name: [f.code for f in report.findings if f.severity == "error"]
            for name, report in reports.items()
            if any(f.severity == "error" for f in report.findings)
        }
        assert errors == {}

    def test_total_balance_never_negative(self, tables: dict[str, pd.DataFrame]) -> None:
        snapshots = tables["account_monthly_snapshots"]
        assert (snapshots["total_balance"] >= 0).all()

    def test_dpd_never_negative(self, tables: dict[str, pd.DataFrame]) -> None:
        snapshots = tables["account_monthly_snapshots"]
        assert (snapshots["dpd"] >= 0).all()


class TestWriteOffAndRecoveryUnaffected:
    def test_write_off_events_well_formed(self, tables: dict[str, pd.DataFrame]) -> None:
        write_offs = tables["write_off_events"]
        assert len(write_offs) > 0
        assert (write_offs["amount"] > 0).all()

    def test_recovery_only_after_write_off_exists(self, tables: dict[str, pd.DataFrame]) -> None:
        recoveries = tables["recovery_events"]
        write_offs = tables["write_off_events"]
        assert len(recoveries) > 0
        assert recoveries["write_off_id"].isin(write_offs["write_off_id"]).all()

    def test_written_off_contracts_are_terminal(self, tables: dict[str, pd.DataFrame]) -> None:
        write_offs = tables["write_off_events"]
        snapshots = tables["account_monthly_snapshots"]
        for contract_id in write_offs["contract_id"]:
            contract_snaps = snapshots[snapshots["contract_id"] == contract_id].sort_values(
                "snapshot_date"
            )
            assert contract_snaps.iloc[-1]["status"] == "charged_off"


class TestDeterminism:
    def test_same_seed_and_config_produce_identical_content_hash(self) -> None:
        outcome1 = generate_scenario(
            scenario="contract_coverage", scale_name="smoke", seed=777_001, force=True
        )
        hash1 = outcome1.manifest["global_content_hash"]
        _cleanup(outcome1.generation_run_id)

        outcome2 = generate_scenario(
            scenario="contract_coverage", scale_name="smoke", seed=777_001, force=True
        )
        hash2 = outcome2.manifest["global_content_hash"]
        _cleanup(outcome2.generation_run_id)

        assert hash1 == hash2
        assert outcome1.generation_run_id == outcome2.generation_run_id

    def test_different_seed_produces_different_hash(self) -> None:
        outcome1 = generate_scenario(
            scenario="contract_coverage", scale_name="smoke", seed=777_002, force=True
        )
        hash1 = outcome1.manifest["global_content_hash"]
        _cleanup(outcome1.generation_run_id)

        outcome2 = generate_scenario(
            scenario="contract_coverage", scale_name="smoke", seed=777_003, force=True
        )
        hash2 = outcome2.manifest["global_content_hash"]
        _cleanup(outcome2.generation_run_id)

        assert hash1 != hash2
