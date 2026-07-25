"""End-to-end test of credlens.generation.payments.simulate_portfolio_ledger:
the core month-by-month ledger simulation, validated against the REAL
operational contracts in strict mode - not a re-implementation of the
contract rules, the actual same code path `credlens contracts validate`
uses. This is what caught the ALLOCATION_EXCEEDS_PAYMENT floating-point
tolerance bug and the empty-DataFrame column-loss bug during this
phase's own construction (see docs/synthetic_generation_implementation.md
"Real bugs this phase caught").
"""

from __future__ import annotations

import pandas as pd

from credlens.contracts import domain_rules
from credlens.contracts.registry import KNOWN_BUSINESS_RULE_CODES, load_all_contracts
from credlens.generation.applications import apply_cancellations, generate_applications
from credlens.generation.config import load_generation_config
from credlens.generation.contracts import generate_contracts
from credlens.generation.decisions import generate_credit_decisions
from credlens.generation.ids import IdFactory
from credlens.generation.macro import generate_macro_context
from credlens.generation.payments import simulate_portfolio_ledger
from credlens.generation.policies import generate_policy_versions
from credlens.generation.population import generate_customers
from credlens.generation.rng import RunRandomStreams
from credlens.generation.schedules import generate_installments
from credlens.generation.truth import attach_contract_truth, generate_latent_customer_truth

_ALL_CONTRACTS = load_all_contracts()


def _build_full_portfolio(seed: int, n_customers: int) -> dict[str, pd.DataFrame]:
    cfg = load_generation_config()
    streams = RunRandomStreams(seed)
    short = "testhash"

    customers = generate_customers(
        n_customers,
        cfg.period,
        "RUN_test",
        IdFactory("customer", short),
        streams.stream("customers"),
    )
    applications, features, fairness = generate_applications(
        customers,
        cfg.period,
        cfg.applications,
        cfg.population,
        "RUN_test",
        IdFactory("application", short),
        streams.stream("applications"),
    )
    applications = apply_cancellations(
        applications, cfg.applications.cancellation_rate, streams.stream("applications")
    )
    policy_versions = generate_policy_versions(cfg.period, IdFactory("policy_version", short))
    decisions, applications = generate_credit_decisions(
        applications,
        features,
        policy_versions["policy_version_id"].iloc[0],
        cfg.policy,
        cfg.population.declared_income_min,
        cfg.population.declared_income_max,
        IdFactory("decision", short),
        streams.stream("decisions"),
    )
    contracts_df = generate_contracts(
        applications,
        decisions,
        cfg.booking,
        cfg.contract,
        cfg.currency_unit,
        IdFactory("contract", short),
        streams.stream("booking"),
    )
    installments = generate_installments(contracts_df, IdFactory("installment", short))
    customer_truth = generate_latent_customer_truth(customers, streams.stream("truth"))
    contract_truth = attach_contract_truth(contracts_df, customer_truth)

    id_factories = {
        "payment": IdFactory("payment", short),
        "allocation": IdFactory("allocation", short),
        "write_off": IdFactory("write_off", short),
        "collection_event": IdFactory("collection_event", short),
        "recovery": IdFactory("recovery", short),
    }
    rng_streams = {
        "payments": streams.stream("payments"),
        "collections": streams.stream("collections"),
        "write_off": streams.stream("write_off"),
        "recovery": streams.stream("recovery"),
    }
    ledger = simulate_portfolio_ledger(
        contracts_df,
        installments,
        contract_truth,
        cfg,
        pd.Timestamp(cfg.period.end),
        id_factories,
        rng_streams,
    )
    macro_context = generate_macro_context(
        pd.Timestamp(cfg.period.start), pd.Timestamp(cfg.period.end)
    )

    generation_runs = pd.DataFrame(
        {
            "generation_run_id": ["RUN_test"],
            "generator_version": ["0.4.0"],
            "config_version": ["1"],
            "seed": [seed],
            "scenario": ["baseline"],
            "period_start": [cfg.period.start.isoformat()],
            "period_end": [cfg.period.end.isoformat()],
            "generated_at": [pd.Timestamp.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")],
            "config_hash": ["deadbeef"],
            "contract_version_set": ["v1"],
            "status": ["completed"],
            "planned_customers": [n_customers],
            "planned_applications": [len(applications)],
            "is_synthetic": [True],
            "scale": ["smoke"],
        }
    )

    return {
        "generation_runs": generation_runs,
        "customers": customers,
        "applications": applications,
        "application_features": features,
        "fairness_attributes": fairness,
        "policy_versions": policy_versions,
        "credit_decisions": decisions,
        "contracts": contracts_df,
        "installments": ledger.installments,
        "payments": ledger.payments,
        "payment_allocations": ledger.payment_allocations,
        "account_monthly_snapshots": ledger.account_monthly_snapshots,
        "collection_events": ledger.collection_events,
        "write_off_events": ledger.write_off_events,
        "recovery_events": ledger.recovery_events,
        "macro_context_monthly": macro_context,
    }


def _strict_errors(tables: dict[str, pd.DataFrame]) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    for name, df in tables.items():
        contract = _ALL_CONTRACTS[name]
        findings = list(domain_rules.check_all(df, contract, tables, mode="strict"))
        for rule in contract.business_rules:
            findings.extend(KNOWN_BUSINESS_RULE_CODES[rule.code](tables, contract.name))  # type: ignore[operator]
        error_codes = [f.code for f in findings if f.severity == "error"]
        if error_codes:
            errors[name] = error_codes
    return errors


class TestFullPortfolioPassesRealContracts:
    """The single most important integration test in this phase: real
    generated output, validated by the real Phase 3 contract-validation
    code (not a hand-rolled re-check), across every one of the 16
    operational contracts, at two different seeds/scales."""

    def test_smoke_scale_seed_42_passes_every_operational_contract(self) -> None:
        tables = _build_full_portfolio(seed=42, n_customers=200)
        errors = _strict_errors(tables)
        assert errors == {}, f"Contract validation errors: {errors}"

    def test_smoke_scale_different_seed_also_passes(self) -> None:
        tables = _build_full_portfolio(seed=777, n_customers=150)
        errors = _strict_errors(tables)
        assert errors == {}, f"Contract validation errors: {errors}"


class TestRetentionRuleAndDpdHonesty:
    def test_no_contract_has_a_snapshot_after_its_terminal_month(self) -> None:
        tables = _build_full_portfolio(seed=42, n_customers=300)
        snapshots = tables["account_monthly_snapshots"]
        terminal = snapshots[snapshots["status"].isin(["settled", "closed", "charged_off"])]
        for contract_id, group in snapshots.groupby("contract_id"):
            terminal_dates = group.loc[
                group["status"].isin(["settled", "closed", "charged_off"]), "snapshot_date"
            ]
            if terminal_dates.empty:
                continue
            first_terminal = min(terminal_dates)
            later = group[group["snapshot_date"] > first_terminal]
            assert later.empty, f"{contract_id} has a snapshot after its terminal month"
        del terminal  # only used for the emptiness sanity check above

    def test_no_snapshot_ever_uses_the_old_999_sentinel(self) -> None:
        tables = _build_full_portfolio(seed=42, n_customers=300)
        snapshots = tables["account_monthly_snapshots"]
        assert not (snapshots["dpd"] == 999).any()

    def test_written_off_contracts_have_a_real_positive_dpd(self) -> None:
        tables = _build_full_portfolio(seed=42, n_customers=400)
        write_offs = tables["write_off_events"]
        if write_offs.empty:
            return  # this seed/scale produced no write-offs - not a failure
        snapshots = tables["account_monthly_snapshots"]
        charged_off = snapshots[snapshots["status"] == "charged_off"]
        assert (charged_off["dpd"] > 0).all()

    def test_no_negative_balances_anywhere(self) -> None:
        tables = _build_full_portfolio(seed=42, n_customers=200)
        snapshots = tables["account_monthly_snapshots"]
        for column in (
            "outstanding_principal",
            "outstanding_interest",
            "outstanding_fees",
            "total_balance",
            "cumulative_paid",
            "cumulative_write_off",
        ):
            assert (snapshots[column] >= 0).all(), f"{column} went negative"


class TestPaymentsNeverExceedTolerance:
    def test_allocation_sums_never_exceed_payment_amount(self) -> None:
        tables = _build_full_portfolio(seed=42, n_customers=300)
        allocations = tables["payment_allocations"]
        payments = tables["payments"]
        if allocations.empty:
            return
        totals = allocations.groupby("payment_id")["allocated_total"].sum()
        amounts = payments.set_index("payment_id")["amount"]
        comparison = totals.to_frame("allocated").join(amounts.to_frame("amount"))
        assert (comparison["allocated"] - comparison["amount"] <= 0.01).all()
