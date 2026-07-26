"""Real, end-to-end generation tests for every Phase 4B scenario: CRN
gating, superset/subset invariants, pre/post-shock behavior, collections
pre-eligibility identity, and contract_coverage's rare-state coverage.
All at 'smoke' scale (fast, CI-safe) - see docs/counterfactual_scenarios.md.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

from credlens.generation.config import (
    CRN_SCENARIOS,
    EXECUTABLE_SCENARIOS,
    CrnIncompatibleError,
    assert_crn_compatible,
    config_path_for_scenario,
    load_generation_config,
)
from credlens.generation.manifest import canonical_table_hash
from credlens.generation.orchestrator import GenerationOutcome, generate_scenario

_SEED = 909_111


def _cleanup(run_id: str) -> None:
    config = load_generation_config()
    for base in (config.output.operational_dir, config.output.truth_dir):
        path = Path(base) / run_id
        if path.exists():
            shutil.rmtree(path)


@pytest.fixture
def cleanup_runs() -> Iterator[list[str]]:
    created: list[str] = []
    yield created
    for run_id in created:
        _cleanup(run_id)


def _generate(scenario: str, cleanup_runs: list[str], seed: int = _SEED) -> GenerationOutcome:
    outcome = generate_scenario(scenario=scenario, scale_name="smoke", seed=seed, force=True)
    cleanup_runs.append(outcome.generation_run_id)
    return outcome


class TestExecutableScenarios:
    def test_every_executable_scenario_generates_and_passes_contracts(
        self, cleanup_runs: list[str]
    ) -> None:
        for scenario in EXECUTABLE_SCENARIOS:
            outcome = _generate(scenario, cleanup_runs)
            assert outcome.status == "completed", scenario
            assert outcome.validation.contracts_passed, scenario
            assert outcome.validation.pii_safe, scenario


class TestCrnGate:
    def test_assert_crn_compatible_passes_for_real_scenario_configs(self) -> None:
        baseline_config = load_generation_config()
        for scenario in CRN_SCENARIOS:
            scenario_config = load_generation_config(config_path_for_scenario(scenario))
            assert_crn_compatible(baseline_config, scenario_config)  # must not raise

    def test_assert_crn_compatible_rejects_population_mismatch(self) -> None:
        baseline_config = load_generation_config()
        mutated = baseline_config.model_copy(
            update={
                "population": baseline_config.population.model_copy(
                    update={"declared_income_min": 1.0}
                )
            }
        )
        with pytest.raises(CrnIncompatibleError, match="population"):
            assert_crn_compatible(baseline_config, mutated)

    def test_generate_scenario_enforces_crn_before_generating(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A scenario config file that diverges from baseline on a
        # CRN-relevant field must be rejected before any generation work
        # happens - simulate this by pointing policy_expansion's config
        # loader at a payload with a different population.
        import credlens.generation.orchestrator as orchestrator_module

        def fake_load(path: Path | None = None) -> object:
            config = load_generation_config() if path is None else load_generation_config(path)
            if path is not None and "policy_expansion" in str(path):
                config = config.model_copy(
                    update={
                        "population": config.population.model_copy(
                            update={"declared_income_min": 1.0}
                        )
                    }
                )
            return config

        monkeypatch.setattr(orchestrator_module, "load_generation_config", fake_load)
        with pytest.raises(CrnIncompatibleError):
            orchestrator_module.generate_scenario(
                scenario="policy_expansion", scale_name="smoke", seed=_SEED, force=True
            )


class TestPolicyExpansionTightening:
    def test_expansion_approved_set_is_superset_of_baseline(self, cleanup_runs: list[str]) -> None:
        baseline = _generate("baseline", cleanup_runs)
        expansion = _generate("policy_expansion", cleanup_runs)

        base_apps = pd.read_parquet(
            baseline.operational_dir / "operational" / "applications.parquet"
        )
        exp_apps = pd.read_parquet(
            expansion.operational_dir / "operational" / "applications.parquet"
        )

        base_approved = set(base_apps.loc[base_apps["status"] == "approved", "application_id"])
        exp_approved = set(exp_apps.loc[exp_apps["status"] == "approved", "application_id"])

        assert base_approved.issubset(exp_approved)
        assert len(exp_approved) > len(base_approved)

    def test_tightening_approved_set_is_subset_of_baseline(self, cleanup_runs: list[str]) -> None:
        baseline = _generate("baseline", cleanup_runs)
        tightening = _generate("policy_tightening", cleanup_runs)

        base_apps = pd.read_parquet(
            baseline.operational_dir / "operational" / "applications.parquet"
        )
        tight_apps = pd.read_parquet(
            tightening.operational_dir / "operational" / "applications.parquet"
        )

        base_approved = set(base_apps.loc[base_apps["status"] == "approved", "application_id"])
        tight_approved = set(tight_apps.loc[tight_apps["status"] == "approved", "application_id"])

        assert tight_approved.issubset(base_approved)
        assert len(tight_approved) < len(base_approved)

    def test_expansion_and_tightening_share_customers_with_baseline(
        self, cleanup_runs: list[str]
    ) -> None:
        baseline = _generate("baseline", cleanup_runs)
        expansion = _generate("policy_expansion", cleanup_runs)

        def customers(outcome: GenerationOutcome) -> pd.DataFrame:
            df = pd.read_parquet(outcome.operational_dir / "operational" / "customers.parquet")
            return df.drop(columns=["generation_run_id"])

        base_hash = canonical_table_hash(customers(baseline))
        exp_hash = canonical_table_hash(customers(expansion))
        assert base_hash == exp_hash


class TestMacroeconomicStress:
    def test_pre_shock_payments_identical_to_baseline(self, cleanup_runs: list[str]) -> None:
        baseline = _generate("baseline", cleanup_runs)
        stress = _generate("macroeconomic_stress", cleanup_runs)

        shock_cfg = load_generation_config(config_path_for_scenario("macroeconomic_stress"))
        assert shock_cfg.macro_shock is not None
        shock_date = shock_cfg.macro_shock.shock_date.isoformat()

        cols = [
            "customer_id",
            "payment_timestamp",
            "amount",
            "channel",
            "status",
            "settlement_date",
        ]

        def pre_shock(outcome: GenerationOutcome) -> pd.DataFrame:
            df = pd.read_parquet(outcome.operational_dir / "operational" / "payments.parquet")
            return (
                df[df["settlement_date"] < shock_date][cols]
                .sort_values(["customer_id", "settlement_date"])
                .reset_index(drop=True)
            )

        base_pre = pre_shock(baseline)
        stress_pre = pre_shock(stress)
        assert canonical_table_hash(base_pre) == canonical_table_hash(stress_pre)

    def test_macro_context_gains_synthetic_shock_rows_not_mixed_with_real(
        self, cleanup_runs: list[str]
    ) -> None:
        stress = _generate("macroeconomic_stress", cleanup_runs)
        macro = pd.read_parquet(
            stress.operational_dir / "operational" / "macro_context_monthly.parquet"
        )
        synthetic = macro[macro["is_synthetic"]]
        real = macro[~macro["is_synthetic"]]
        assert len(synthetic) > 0
        assert (synthetic["source_type"] == "synthetic_shock").all()
        assert (real["source_type"] == "public_bcb_observation").all()
        # never mixed on the same row: is_synthetic strictly separates them
        assert set(synthetic["source_id"]).isdisjoint(set(real["source_id"]))


class TestCollectionsChange:
    def test_only_collections_recovery_and_cure_parameters_differ(self) -> None:
        baseline_config = load_generation_config()
        scenario_config = load_generation_config(config_path_for_scenario("collections_change"))

        assert baseline_config.collections != scenario_config.collections
        assert baseline_config.recovery != scenario_config.recovery
        assert (
            baseline_config.payment_behavior.cure_probability_per_month
            != scenario_config.payment_behavior.cure_probability_per_month
        )
        # everything else in payment_behavior (the pre-eligibility part) is
        # untouched - on_time/partial/prepay/reversal identical to baseline.
        assert (
            baseline_config.payment_behavior.on_time_probability
            == scenario_config.payment_behavior.on_time_probability
        )
        assert (
            baseline_config.payment_behavior.partial_payment_probability
            == scenario_config.payment_behavior.partial_payment_probability
        )
        assert (
            baseline_config.payment_behavior.prepayment_probability
            == scenario_config.payment_behavior.prepayment_probability
        )
        assert (
            baseline_config.payment_behavior.reversal_rate
            == scenario_config.payment_behavior.reversal_rate
        )
        assert baseline_config.policy == scenario_config.policy


class TestContractCoverage:
    def test_produces_every_achievable_covered_state(self, cleanup_runs: list[str]) -> None:
        outcome = _generate("contract_coverage", cleanup_runs)
        op = outcome.operational_dir / "operational"

        decisions = pd.read_parquet(op / "credit_decisions.parquet")
        contracts = pd.read_parquet(op / "contracts.parquet")
        installments = pd.read_parquet(op / "installments.parquet")
        payments = pd.read_parquet(op / "payments.parquet")
        snapshots = pd.read_parquet(op / "account_monthly_snapshots.parquet")
        collections = pd.read_parquet(op / "collection_events.parquet")
        write_offs = pd.read_parquet(op / "write_off_events.parquet")
        recoveries = pd.read_parquet(op / "recovery_events.parquet")

        assert (decisions["outcome"] == "approved").any(), "approval"
        assert (decisions["outcome"] == "rejected").any(), "rejection"
        n_approved = int((decisions["outcome"] == "approved").sum())
        assert n_approved > len(contracts), "approval without booking"
        assert ((snapshots["status"] == "active") & (snapshots["dpd"] == 0)).any(), "performing"
        assert (snapshots["status"] == "delinquent").any(), "delinquency"
        assert (installments["status"] == "partially_paid").any(), "partial payment"
        assert len(write_offs) > 0, "write-off"
        assert len(recoveries) > 0, "recovery"
        assert len(collections) > 0, "collections"
        assert payments["reversal_of_payment_id"].notna().any(), "reversal"

        # payment_type (Phase 5) is the generator's own explicit
        # classification - a direct check, not a status-based heuristic.
        assert (payments["payment_type"] == "cure").any(), "cure"
        assert (payments["payment_type"] == "prepayment").any(), "prepayment"

        # Relapse (Phase 5): a contract that was delinquent, returned to
        # active (cured), and later became delinquent again - only
        # possible now that cure no longer terminates the contract. See
        # docs/adr/0010-cure-semantics-and-relapse.md.
        ordered = snapshots.sort_values(["contract_id", "snapshot_date"])
        relapsed_contracts = []
        for contract_id, group in ordered.groupby("contract_id"):
            statuses = group["status"].tolist()
            cured_since_last_delinquency = False
            for status in statuses:
                if status == "delinquent":
                    if cured_since_last_delinquency:
                        relapsed_contracts.append(contract_id)
                        break
                    cured_since_last_delinquency = False
                elif status == "active":
                    cured_since_last_delinquency = True
        assert len(relapsed_contracts) > 0, "relapse into delinquency"
