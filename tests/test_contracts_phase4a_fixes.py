"""Dedicated tests for the three Phase 3 conceptual fixes mandated at the
start of Phase 4A (see docs/adr/0008-macro-context-provenance.md and
docs/adr/0009-dpd-sentinel-removal.md):

1. macro_context_monthly's classification no longer conflates real BCB
   observations with (future) synthetic shocks - every row self-declares
   its own provenance, and macro_context_provenance_consistent enforces
   it.
2. DPD=999 (or any other sentinel) is rejected: dpd must always be the
   real, ledger-derived days-past-due, and no snapshot may exist after a
   contract's status is first observed as terminal.
3. account_monthly_snapshots.cumulative_paid/total_balance/
   cumulative_write_off/dpd are now reconciled against
   installments/payments/payment_allocations/write_off_events, closing
   the gap Phase 3 explicitly declared and left open.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from credlens.contracts import financial_rules, relational_rules, temporal_rules
from credlens.contracts.loader import load_contract


class TestMacroContextProvenance:
    def test_real_contract_classification_is_public_market_context(self) -> None:
        contract = load_contract(Path("contracts/operational/macro_context_monthly.yaml"))
        assert contract.classification.value == "public_market_context"

    def test_contract_declares_row_level_provenance_columns(self) -> None:
        contract = load_contract(Path("contracts/operational/macro_context_monthly.yaml"))
        for column in ("source_type", "source_id", "is_synthetic", "unit"):
            assert column in contract.column_names

    def test_public_observation_flagged_synthetic_is_rejected(self) -> None:
        df = pd.DataFrame(
            {
                "source_type": ["public_bcb_observation"],
                "source_id": ["bcb-sgs-20570"],
                "series_code": [20570],
                "reference_date": ["2024-01-01"],
                "is_synthetic": [True],  # inconsistent: real BCB row can't be synthetic
            }
        )
        findings = relational_rules.macro_context_provenance_consistent(
            {"macro_context_monthly": df}, "macro_context_monthly"
        )
        assert len(findings) == 1
        assert findings[0].code == "MACRO_CONTEXT_PROVENANCE_INCONSISTENT"

    def test_public_observation_with_null_series_code_is_rejected(self) -> None:
        df = pd.DataFrame(
            {
                "source_type": ["public_bcb_observation"],
                "source_id": ["bcb-sgs-20570"],
                "series_code": [None],
                "reference_date": ["2024-01-01"],
                "is_synthetic": [False],
            }
        )
        findings = relational_rules.macro_context_provenance_consistent(
            {"macro_context_monthly": df}, "macro_context_monthly"
        )
        assert len(findings) == 1

    def test_synthetic_shock_flagged_non_synthetic_is_rejected(self) -> None:
        df = pd.DataFrame(
            {
                "source_type": ["synthetic_shock"],
                "source_id": ["stress-v1"],
                "series_code": [None],
                "reference_date": ["2024-01-01"],
                "is_synthetic": [False],  # inconsistent: a shock must be marked synthetic
            }
        )
        findings = relational_rules.macro_context_provenance_consistent(
            {"macro_context_monthly": df}, "macro_context_monthly"
        )
        assert len(findings) == 1

    def test_consistent_real_and_synthetic_rows_pass(self) -> None:
        df = pd.DataFrame(
            {
                "source_type": ["public_bcb_observation", "synthetic_shock", "derived_index"],
                "source_id": ["bcb-sgs-20570", "stress-v1", "idx-1"],
                "series_code": [20570, None, None],
                "is_synthetic": [False, True, True],
            }
        )
        findings = relational_rules.macro_context_provenance_consistent(
            {"macro_context_monthly": df}, "macro_context_monthly"
        )
        assert findings == []


class TestNoSnapshotAfterTerminalStatus:
    def test_snapshot_after_terminal_status_is_flagged(self) -> None:
        df = pd.DataFrame(
            {
                "contract_id": ["ctr-1", "ctr-1", "ctr-1"],
                "snapshot_date": ["2024-01-31", "2024-02-29", "2024-03-31"],
                "status": ["delinquent", "charged_off", "charged_off"],
            }
        )
        findings = temporal_rules.no_snapshot_after_terminal_status(
            {"account_monthly_snapshots": df}, "account_monthly_snapshots"
        )
        assert len(findings) == 1
        assert findings[0].code == "SNAPSHOT_AFTER_TERMINAL_STATUS"
        assert findings[0].count == 1  # only the 03-31 row is "after" the terminal 02-29 one

    def test_terminal_status_as_last_snapshot_is_fine(self) -> None:
        df = pd.DataFrame(
            {
                "contract_id": ["ctr-1", "ctr-1"],
                "snapshot_date": ["2024-01-31", "2024-02-29"],
                "status": ["delinquent", "charged_off"],
            }
        )
        findings = temporal_rules.no_snapshot_after_terminal_status(
            {"account_monthly_snapshots": df}, "account_monthly_snapshots"
        )
        assert findings == []

    def test_never_terminal_is_fine(self) -> None:
        df = pd.DataFrame(
            {
                "contract_id": ["ctr-1", "ctr-1"],
                "snapshot_date": ["2024-01-31", "2024-02-29"],
                "status": ["active", "delinquent"],
            }
        )
        findings = temporal_rules.no_snapshot_after_terminal_status(
            {"account_monthly_snapshots": df}, "account_monthly_snapshots"
        )
        assert findings == []

    def test_different_contracts_do_not_interfere(self) -> None:
        df = pd.DataFrame(
            {
                "contract_id": ["ctr-1", "ctr-2"],
                "snapshot_date": ["2024-02-29", "2024-03-31"],
                "status": ["charged_off", "active"],
            }
        )
        findings = temporal_rules.no_snapshot_after_terminal_status(
            {"account_monthly_snapshots": df}, "account_monthly_snapshots"
        )
        assert findings == []


class TestDpdSentinelRejection:
    """The direct fix for the Phase 3 fixture's DPD=999: a fabricated DPD
    incompatible with the real installment due-date chronology must be
    rejected, and the reconciliation must compute the real value."""

    def test_dpd_999_incompatible_with_chronology_is_rejected(self) -> None:
        installments = pd.DataFrame(
            {
                "installment_id": ["inst-1"],
                "contract_id": ["ctr-1"],
                "due_date": ["2024-02-12"],
                "scheduled_total": [176],
            }
        )
        payments = pd.DataFrame(
            {"payment_id": [], "status": [], "settlement_date": [], "reversal_of_payment_id": []}
        )
        allocations = pd.DataFrame({"payment_id": [], "installment_id": [], "allocated_total": []})
        snapshots = pd.DataFrame(
            {
                "contract_id": ["ctr-1"],
                "snapshot_date": ["2024-06-30"],
                "dpd": [999],
                "delinquency_bucket": ["90+"],
            }
        )
        tables = {
            "account_monthly_snapshots": snapshots,
            "installments": installments,
            "payments": payments,
            "payment_allocations": allocations,
        }

        findings = financial_rules.snapshot_dpd_reconciled_with_installments(
            tables, "account_monthly_snapshots"
        )

        assert len(findings) == 1
        assert findings[0].code == "SNAPSHOT_DPD_MISMATCH"

    def test_real_ledger_derived_dpd_is_accepted(self) -> None:
        """139 = (2024-06-30 - 2024-02-12).days - the real value, not a
        sentinel - must NOT be flagged."""
        installments = pd.DataFrame(
            {
                "installment_id": ["inst-1"],
                "contract_id": ["ctr-1"],
                "due_date": ["2024-02-12"],
                "scheduled_total": [176],
            }
        )
        payments = pd.DataFrame(
            {"payment_id": [], "status": [], "settlement_date": [], "reversal_of_payment_id": []}
        )
        allocations = pd.DataFrame({"payment_id": [], "installment_id": [], "allocated_total": []})
        snapshots = pd.DataFrame(
            {
                "contract_id": ["ctr-1"],
                "snapshot_date": ["2024-06-30"],
                "dpd": [139],
                "delinquency_bucket": ["90+"],
            }
        )
        tables = {
            "account_monthly_snapshots": snapshots,
            "installments": installments,
            "payments": payments,
            "payment_allocations": allocations,
        }

        findings = financial_rules.snapshot_dpd_reconciled_with_installments(
            tables, "account_monthly_snapshots"
        )

        assert findings == []

    def test_not_yet_due_installment_never_contributes_dpd(self) -> None:
        installments = pd.DataFrame(
            {
                "installment_id": ["inst-1"],
                "contract_id": ["ctr-1"],
                "due_date": ["2024-03-03"],  # after the snapshot below
                "scheduled_total": [100],
            }
        )
        payments = pd.DataFrame(
            {"payment_id": [], "status": [], "settlement_date": [], "reversal_of_payment_id": []}
        )
        allocations = pd.DataFrame({"payment_id": [], "installment_id": [], "allocated_total": []})
        snapshots = pd.DataFrame(
            {
                "contract_id": ["ctr-1"],
                "snapshot_date": ["2024-02-29"],
                "dpd": [0],
                "delinquency_bucket": ["current"],
            }
        )
        tables = {
            "account_monthly_snapshots": snapshots,
            "installments": installments,
            "payments": payments,
            "payment_allocations": allocations,
        }

        findings = financial_rules.snapshot_dpd_reconciled_with_installments(
            tables, "account_monthly_snapshots"
        )

        assert findings == []


class TestSnapshotLedgerReconciliation:
    def _tables(self) -> dict[str, pd.DataFrame]:
        installments = pd.DataFrame(
            {
                "installment_id": ["inst-1"],
                "contract_id": ["ctr-1"],
                "due_date": ["2024-02-03"],
                "scheduled_total": [100],
            }
        )
        payments = pd.DataFrame(
            {
                "payment_id": ["pay-1"],
                "status": ["settled"],
                "settlement_date": ["2024-02-01"],
                "reversal_of_payment_id": [None],
            }
        )
        allocations = pd.DataFrame(
            {"payment_id": ["pay-1"], "installment_id": ["inst-1"], "allocated_total": [100]}
        )
        write_offs = pd.DataFrame({"contract_id": [], "write_off_date": [], "amount": []})
        return {
            "installments": installments,
            "payments": payments,
            "payment_allocations": allocations,
            "write_off_events": write_offs,
        }

    def test_cumulative_paid_mismatch_is_flagged(self) -> None:
        tables = self._tables()
        tables["account_monthly_snapshots"] = pd.DataFrame(
            {"contract_id": ["ctr-1"], "snapshot_date": ["2024-02-29"], "cumulative_paid": [50]}
        )
        findings = financial_rules.snapshot_cumulative_paid_reconciled(
            tables, "account_monthly_snapshots"
        )
        assert len(findings) == 1
        assert findings[0].code == "SNAPSHOT_CUMULATIVE_PAID_MISMATCH"

    def test_cumulative_paid_matching_ledger_is_fine(self) -> None:
        tables = self._tables()
        tables["account_monthly_snapshots"] = pd.DataFrame(
            {"contract_id": ["ctr-1"], "snapshot_date": ["2024-02-29"], "cumulative_paid": [100]}
        )
        findings = financial_rules.snapshot_cumulative_paid_reconciled(
            tables, "account_monthly_snapshots"
        )
        assert findings == []

    def test_balance_mismatch_is_flagged(self) -> None:
        tables = self._tables()
        tables["account_monthly_snapshots"] = pd.DataFrame(
            {"contract_id": ["ctr-1"], "snapshot_date": ["2024-02-29"], "total_balance": [999]}
        )
        findings = financial_rules.snapshot_balance_reconciled_with_ledger(
            tables, "account_monthly_snapshots"
        )
        assert len(findings) == 1
        assert findings[0].code == "SNAPSHOT_BALANCE_RECONCILIATION_FAILED"

    def test_balance_matching_ledger_after_full_payment_is_zero(self) -> None:
        tables = self._tables()
        tables["account_monthly_snapshots"] = pd.DataFrame(
            {"contract_id": ["ctr-1"], "snapshot_date": ["2024-02-29"], "total_balance": [0]}
        )
        findings = financial_rules.snapshot_balance_reconciled_with_ledger(
            tables, "account_monthly_snapshots"
        )
        assert findings == []

    def test_write_off_mismatch_is_flagged(self) -> None:
        tables = self._tables()
        tables["write_off_events"] = pd.DataFrame(
            {"contract_id": ["ctr-1"], "write_off_date": ["2024-02-15"], "amount": [100]}
        )
        tables["account_monthly_snapshots"] = pd.DataFrame(
            {
                "contract_id": ["ctr-1"],
                "snapshot_date": ["2024-02-29"],
                "cumulative_write_off": [0],
            }
        )
        findings = financial_rules.snapshot_write_off_reconciled(
            tables, "account_monthly_snapshots"
        )
        assert len(findings) == 1
        assert findings[0].code == "SNAPSHOT_WRITE_OFF_MISMATCH"

    def test_write_off_matching_events_is_fine(self) -> None:
        tables = self._tables()
        tables["write_off_events"] = pd.DataFrame(
            {"contract_id": ["ctr-1"], "write_off_date": ["2024-02-15"], "amount": [100]}
        )
        tables["account_monthly_snapshots"] = pd.DataFrame(
            {
                "contract_id": ["ctr-1"],
                "snapshot_date": ["2024-02-29"],
                "cumulative_write_off": [100],
            }
        )
        findings = financial_rules.snapshot_write_off_reconciled(
            tables, "account_monthly_snapshots"
        )
        assert findings == []

    def test_reversal_reduces_expected_cumulative_paid(self) -> None:
        tables = self._tables()
        tables["payments"] = pd.concat(
            [
                tables["payments"],
                pd.DataFrame(
                    {
                        "payment_id": ["pay-2"],
                        "status": ["settled"],
                        "settlement_date": ["2024-02-10"],
                        "reversal_of_payment_id": ["pay-1"],
                    }
                ),
            ],
            ignore_index=True,
        )
        tables["payment_allocations"] = pd.concat(
            [
                tables["payment_allocations"],
                pd.DataFrame(
                    {
                        "payment_id": ["pay-2"],
                        "installment_id": ["inst-1"],
                        "allocated_total": [100],
                    }
                ),
            ],
            ignore_index=True,
        )
        tables["account_monthly_snapshots"] = pd.DataFrame(
            {"contract_id": ["ctr-1"], "snapshot_date": ["2024-02-29"], "cumulative_paid": [0]}
        )
        findings = financial_rules.snapshot_cumulative_paid_reconciled(
            tables, "account_monthly_snapshots"
        )
        assert findings == []  # 100 paid, then 100 reversed -> net 0, matches stored 0

    def test_missing_ledger_tables_reports_info(self) -> None:
        snapshots = pd.DataFrame(
            {"contract_id": ["ctr-1"], "snapshot_date": ["2024-02-29"], "cumulative_paid": [0]}
        )
        findings = financial_rules.snapshot_cumulative_paid_reconciled(
            {"account_monthly_snapshots": snapshots}, "account_monthly_snapshots"
        )
        assert len(findings) == 1
        assert findings[0].severity == "info"
        assert findings[0].code == "RULE_NOT_EVALUATED"
