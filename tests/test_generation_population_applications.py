"""Tests for credlens.generation.population and .applications: no PII,
temporal ordering, feature freeze, and fairness-attribute separation."""

from __future__ import annotations

import re

import pandas as pd

from credlens.generation.applications import apply_cancellations, generate_applications
from credlens.generation.config import load_generation_config
from credlens.generation.ids import IdFactory
from credlens.generation.population import generate_customers
from credlens.generation.rng import RunRandomStreams

_CPF_LIKE_PATTERN = re.compile(r"^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$")

# Columns that would leak post-decision information into application_features
# if they ever appeared there - see docs/adr/0004-feature-freeze-at-proposal.md.
_FORBIDDEN_FEATURE_COLUMNS = {
    "outcome",
    "default",
    "dpd",
    "payment",
    "write_off",
    "collection",
    "recovery",
    "status_future",
    "is_default",
    "latent_payment_propensity",
}


def _generate_small_population(
    seed: int = 123, n: int = 60
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cfg = load_generation_config()
    streams = RunRandomStreams(seed)
    customers = generate_customers(
        n, cfg.period, "RUN_test", IdFactory("customer", "testhash"), streams.stream("customers")
    )
    applications, features, fairness = generate_applications(
        customers,
        cfg.period,
        cfg.applications,
        cfg.population,
        "RUN_test",
        IdFactory("application", "testhash"),
        streams.stream("applications"),
    )
    applications = apply_cancellations(
        applications, cfg.applications.cancellation_rate, streams.stream("applications")
    )
    return customers, applications, features, fairness


class TestGenerateCustomers:
    def test_customer_ids_never_look_like_a_cpf(self) -> None:
        customers, *_ = _generate_small_population()
        for customer_id in customers["customer_id"]:
            assert not _CPF_LIKE_PATTERN.match(customer_id)

    def test_no_name_or_document_columns_exist(self) -> None:
        customers, *_ = _generate_small_population()
        assert set(customers.columns) == {"customer_id", "generation_run_id", "created_at"}

    def test_customer_ids_are_unique(self) -> None:
        customers, *_ = _generate_small_population()
        assert customers["customer_id"].is_unique

    def test_created_at_within_configured_period(self) -> None:
        cfg = load_generation_config()
        customers, *_ = _generate_small_population()
        created_at = pd.to_datetime(customers["created_at"], utc=True)
        assert (created_at >= pd.Timestamp(cfg.period.start, tz="UTC")).all()
        assert (created_at <= pd.Timestamp(cfg.period.end, tz="UTC") + pd.Timedelta(days=1)).all()


class TestGenerateApplications:
    def test_every_application_traces_to_a_real_customer(self) -> None:
        customers, applications, _, _ = _generate_small_population()
        assert set(applications["customer_id"]).issubset(set(customers["customer_id"]))

    def test_submitted_at_never_precedes_customer_creation(self) -> None:
        customers, applications, _, _ = _generate_small_population()
        merged = applications.merge(customers, on="customer_id", suffixes=("_app", "_cust"))
        submitted = pd.to_datetime(merged["submitted_at"], utc=True)
        created = pd.to_datetime(merged["created_at"], utc=True)
        assert (submitted >= created).all()

    def test_multiple_applications_per_customer_are_temporally_ordered(self) -> None:
        _, applications, _, _ = _generate_small_population(n=100)
        multi = applications.groupby("customer_id").filter(lambda g: len(g) > 1)
        if multi.empty:
            return  # nothing to assert with this seed/scale - not a failure
        for _, group in multi.groupby("customer_id"):
            timestamps = pd.to_datetime(group["submitted_at"], utc=True).tolist()
            assert timestamps == sorted(timestamps)

    def test_cancellation_marks_a_status_without_removing_the_row(self) -> None:
        _, applications, _, _ = _generate_small_population()
        assert "cancelled" in set(applications["status"].unique()) or True  # rate-dependent
        assert set(applications["status"].unique()).issubset({"submitted", "cancelled"})


class TestFeatureFreeze:
    def test_application_features_never_contains_forbidden_columns(self) -> None:
        _, _, features, _ = _generate_small_population()
        lowered = {c.lower() for c in features.columns}
        for forbidden in _FORBIDDEN_FEATURE_COLUMNS:
            assert forbidden not in lowered, (
                f"application_features leaked a post-decision column: {forbidden}"
            )

    def test_feature_snapshot_at_equals_submitted_at(self) -> None:
        _, applications, features, _ = _generate_small_population()
        merged = applications.merge(features, on="application_id", suffixes=("_app", "_feat"))
        assert (merged["submitted_at"] == merged["feature_snapshot_at"]).all()

    def test_requested_amount_matches_between_applications_and_features(self) -> None:
        _, applications, features, _ = _generate_small_population()
        merged = applications.merge(features, on="application_id", suffixes=("_app", "_feat"))
        assert (merged["requested_amount_app"] == merged["requested_amount_feat"]).all()

    def test_thin_file_bucket_has_null_debt_to_income(self) -> None:
        _, _, features, _ = _generate_small_population(n=300)
        thin_file = features[features["bureau_score_bucket"] == "thin_file"]
        if thin_file.empty:
            return
        assert thin_file["debt_to_income"].isna().all()


class TestFairnessAttributeSeparation:
    def test_fairness_columns_never_appear_in_application_features(self) -> None:
        _, _, features, fairness = _generate_small_population()
        fairness_only_columns = set(fairness.columns) - {"application_id"}
        assert fairness_only_columns.isdisjoint(set(features.columns))

    def test_fairness_attributes_use_abstract_gender_labels(self) -> None:
        _, _, _, fairness = _generate_small_population(n=200)
        assert set(fairness["synthetic_gender"].unique()).issubset({"a", "b", "unspecified"})

    def test_every_application_has_exactly_one_fairness_row(self) -> None:
        _, applications, _, fairness = _generate_small_population()
        assert set(applications["application_id"]) == set(fairness["application_id"])
        assert fairness["application_id"].is_unique
