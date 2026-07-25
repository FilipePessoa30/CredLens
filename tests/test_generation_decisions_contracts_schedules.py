"""Tests for credlens.generation.decisions, .contracts, and .schedules:
the decision score's separation from the truth layer, booking, and
amortization-schedule rounding/reconciliation."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd

from credlens.generation.applications import apply_cancellations, generate_applications
from credlens.generation.config import load_generation_config
from credlens.generation.contracts import generate_contracts
from credlens.generation.decisions import compute_decision_score, generate_credit_decisions
from credlens.generation.ids import IdFactory
from credlens.generation.policies import generate_policy_versions
from credlens.generation.population import generate_customers
from credlens.generation.rng import RunRandomStreams
from credlens.generation.schedules import generate_installments


def _pipeline(
    seed: int = 55, n: int = 120
) -> tuple[
    object, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame
]:
    cfg = load_generation_config()
    streams = RunRandomStreams(seed)
    customers = generate_customers(
        n, cfg.period, "RUN_test", IdFactory("customer", "h"), streams.stream("customers")
    )
    applications, features, _fairness = generate_applications(
        customers,
        cfg.period,
        cfg.applications,
        cfg.population,
        "RUN_test",
        IdFactory("application", "h"),
        streams.stream("applications"),
    )
    applications = apply_cancellations(
        applications, cfg.applications.cancellation_rate, streams.stream("applications")
    )
    policy_versions = generate_policy_versions(cfg.period, IdFactory("policy_version", "h"))
    decisions, applications = generate_credit_decisions(
        applications,
        features,
        policy_versions["policy_version_id"].iloc[0],
        cfg.policy,
        cfg.population.declared_income_min,
        cfg.population.declared_income_max,
        IdFactory("decision", "h"),
        streams.stream("decisions"),
    )
    contracts = generate_contracts(
        applications,
        decisions,
        cfg.booking,
        cfg.contract,
        cfg.currency_unit,
        IdFactory("contract", "h"),
        streams.stream("booking"),
    )
    installments = generate_installments(contracts, IdFactory("installment", "h"))
    return cfg, customers, applications, features, decisions, contracts, installments


class TestDecisionScore:
    def test_score_never_reads_a_truth_layer_column(self) -> None:
        """compute_decision_score's own signature only accepts
        application_features + income bounds - there is no code path for
        it to read a truth-layer table at all, which this test pins by
        construction (calling it with only the visible columns)."""
        features = pd.DataFrame(
            {
                "bureau_score_bucket": ["high", "low"],
                "declared_income": [5000, 1000],
                "debt_to_income": [0.2, 0.8],
            }
        )
        rng = np.random.default_rng(1)
        score = compute_decision_score(features, income_min=0, income_max=10000, rng=rng)
        assert len(score) == 2
        assert score.between(0, 1).all()

    def test_higher_bureau_bucket_scores_higher_on_average(self) -> None:
        rng = np.random.default_rng(1)
        features = pd.DataFrame(
            {
                "bureau_score_bucket": ["high"] * 200 + ["low"] * 200,
                "declared_income": [5000] * 400,
                "debt_to_income": [0.3] * 400,
            }
        )
        score = compute_decision_score(features, income_min=0, income_max=10000, rng=rng)
        assert score[:200].mean() > score[200:].mean()

    def test_credit_decisions_never_has_more_than_one_final_per_application(self) -> None:
        *_, decisions, _, _ = _pipeline()
        assert decisions["is_final"].all()
        assert decisions["application_id"].is_unique  # baseline: exactly one decision per app

    def test_decision_timestamp_never_precedes_submission(self) -> None:
        *_, applications, _, decisions, _, _ = _pipeline()
        merged = decisions.merge(
            applications[["application_id", "submitted_at"]], on="application_id"
        )
        assert (
            pd.to_datetime(merged["decision_timestamp"]) >= pd.to_datetime(merged["submitted_at"])
        ).all()

    def test_rejected_decisions_have_null_approved_fields(self) -> None:
        *_, decisions, _, _ = _pipeline()
        rejected = decisions[decisions["outcome"] == "rejected"]
        assert rejected["approved_amount"].isna().all()
        assert rejected["approved_term_months"].isna().all()
        assert rejected["offered_rate"].isna().all()

    def test_cancelled_applications_never_get_a_decision(self) -> None:
        *_, applications, _, decisions, _, _ = _pipeline()
        cancelled_ids = set(
            applications.loc[applications["status"] == "cancelled", "application_id"]
        )
        assert cancelled_ids.isdisjoint(set(decisions["application_id"]))


class TestContractBooking:
    def test_every_contract_traces_to_an_approved_decision(self) -> None:
        *_, _applications, _, decisions, contracts, _ = _pipeline()
        approved = set(decisions.loc[decisions["outcome"] == "approved", "application_id"])
        assert set(contracts["application_id"]).issubset(approved)

    def test_contract_date_not_before_decision(self) -> None:
        *_, decisions, contracts, _ = _pipeline()
        merged = contracts.merge(
            decisions[["application_id", "decision_timestamp"]], on="application_id"
        )
        assert (
            pd.to_datetime(merged["contract_date"]) >= pd.to_datetime(merged["decision_timestamp"])
        ).all()

    def test_disbursement_not_before_contract(self) -> None:
        *_, contracts, _ = _pipeline()
        assert (
            pd.to_datetime(contracts["disbursement_date"])
            >= pd.to_datetime(contracts["contract_date"])
        ).all()

    def test_currency_unit_is_the_fictional_synthetic_unit(self) -> None:
        *_, contracts, _ = _pipeline()
        if not contracts.empty:
            assert (contracts["currency_unit"] == "credlens_synthetic_unit").all()


class TestAmortizationSchedule:
    def test_principal_sums_reconcile_to_financed_amount(self) -> None:
        *_, contracts, installments = _pipeline()
        sums = installments.groupby("contract_id")["scheduled_principal"].sum()
        merged = contracts.set_index("contract_id")[["financed_amount"]].join(sums)
        assert (merged["financed_amount"] - merged["scheduled_principal"]).abs().max() < 0.01

    def test_scheduled_total_equals_principal_plus_interest_plus_fees(self) -> None:
        *_, installments = _pipeline()
        computed = (
            installments["scheduled_principal"]
            + installments["scheduled_interest"]
            + installments["scheduled_fees"]
        )
        assert (installments["scheduled_total"] - computed).abs().max() < 0.001

    def test_installment_numbers_are_sequential_per_contract(self) -> None:
        *_, installments = _pipeline()
        for _, group in installments.groupby("contract_id"):
            numbers = sorted(group["installment_number"].tolist())
            assert numbers == list(range(1, len(numbers) + 1))

    def test_due_dates_are_one_month_apart(self) -> None:
        *_, installments = _pipeline()
        for _, group in installments.groupby("contract_id"):
            due_dates = pd.to_datetime(group.sort_values("installment_number")["due_date"])
            if len(due_dates) < 2:
                continue
            gaps = due_dates.diff().dropna()
            assert (gaps.dt.days >= 27).all() and (gaps.dt.days <= 32).all()

    def test_zero_installment_contract_produces_no_rows(self) -> None:
        from credlens.generation.schedules import _amortize_one_contract

        assert _amortize_one_contract(Decimal("100"), Decimal("0.05"), 0) == []

    def test_zero_rate_amortization_splits_evenly(self) -> None:
        from credlens.generation.schedules import _amortize_one_contract

        schedule = _amortize_one_contract(Decimal("300"), Decimal("0"), 3)
        assert len(schedule) == 3
        total_principal = sum(p for p, _, _ in schedule)
        assert total_principal == Decimal("300.00")
        assert all(interest == Decimal("0.00") for _, interest, _ in schedule)


def test_empty_contracts_produce_empty_installments() -> None:
    empty_contracts = pd.DataFrame(
        columns=[
            "contract_id",
            "financed_amount",
            "contract_rate",
            "num_installments",
            "first_due_date",
        ]
    )
    installments = generate_installments(empty_contracts, IdFactory("installment", "h"))
    assert installments.empty
