"""Functional/architectural truth-isolation tests (Phase 4B section 4).

The Phase 4A test suite already checked that truth and operational
tables never share column names - explicitly called out in Phase 4A's
own report as insufficient. These tests check the FUNCTIONAL property
instead: perturbing the truth layer must never change credit_decisions,
regardless of how extreme the perturbation is, and the decision code
must have no way to even reach truth.py in the first place.
"""

from __future__ import annotations

import ast
import inspect

import numpy as np
import pandas as pd
import pytest

from credlens.generation import decisions as decisions_module
from credlens.generation.config import PolicyConfig
from credlens.generation.decisions import compute_decision_score, generate_credit_decisions
from credlens.generation.feature_allowlist import (
    DECISION_FEATURE_ALLOWLIST,
    AllowlistError,
    assert_allowlist_is_safe,
    select_decision_features,
)
from credlens.generation.ids import IdFactory


def _features(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "application_id": [f"APP_x_{i:07d}" for i in range(n)],
            "declared_income": np.linspace(1000, 5000, n),
            "debt_to_income": np.linspace(0.1, 0.9, n),
            "employment_months": [12] * n,
            "relationship_months": [0] * n,
            "bureau_score_bucket": (["thin_file", "low", "medium", "high"] * n)[:n],
            "requested_amount": [1000.0] * n,
            "requested_term_months": [12] * n,
            "feature_snapshot_at": ["2024-01-01T00:00:00Z"] * n,
        }
    )


def _applications(features: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "application_id": features["application_id"],
            "customer_id": [f"CUS_x_{i:07d}" for i in range(len(features))],
            "generation_run_id": "RUN_test",
            "submitted_at": ["2024-01-01T00:00:00Z"] * len(features),
            "product": "personal_loan",
            "channel": "app",
            "requested_amount": features["requested_amount"],
            "requested_term_months": features["requested_term_months"],
            "status": "submitted",
        }
    )


class TestStaticIsolation:
    def test_decisions_module_never_imports_truth(self) -> None:
        source = inspect.getsource(decisions_module)
        tree = ast.parse(source)
        imported_modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
            elif isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
        assert not any("truth" in name for name in imported_modules), imported_modules

    def test_compute_decision_score_signature_has_no_truth_parameter(self) -> None:
        sig = inspect.signature(compute_decision_score)
        for name in sig.parameters:
            assert "truth" not in name.lower()
            assert "propensity" not in name.lower()
            assert "latent" not in name.lower()


class TestAllowlist:
    def test_real_allowlist_is_safe(self) -> None:
        assert_allowlist_is_safe()  # must not raise

    def test_allowlist_excludes_behavioral_and_fairness_columns(self) -> None:
        forbidden = {
            "latent_payment_propensity",
            "dpd",
            "write_off_amount",
            "synthetic_gender",
            "age_bracket",
            "region",
        }
        assert forbidden.isdisjoint(DECISION_FEATURE_ALLOWLIST)

    def test_select_decision_features_returns_only_allowlisted_columns(self) -> None:
        features = _features(4)
        selected = select_decision_features(features)
        assert list(selected.columns) == list(DECISION_FEATURE_ALLOWLIST)

    def test_select_decision_features_raises_on_missing_column(self) -> None:
        features = _features(4).drop(columns=["debt_to_income"])
        with pytest.raises(AllowlistError, match="missing allowlisted"):
            select_decision_features(features)

    def test_unsafe_allowlist_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import credlens.generation.feature_allowlist as allowlist_module

        monkeypatch.setattr(
            allowlist_module,
            "DECISION_FEATURE_ALLOWLIST",
            ("bureau_score_bucket", "latent_payment_propensity"),
        )
        with pytest.raises(AllowlistError, match="forbidden pattern"):
            allowlist_module.assert_allowlist_is_safe()


class TestMetamorphicIndependence:
    def test_decisions_identical_under_extreme_truth_perturbation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same features/policy/decision-seed, WILDLY different latent truth
        (all-near-0 vs all-near-1 payment propensity) - credit_decisions
        must come out byte-identical, because compute_decision_score never
        reads truth at all (see TestStaticIsolation)."""
        import credlens.generation.truth as truth_module

        features = _features(30)
        applications = _applications(features)
        policy = PolicyConfig(
            approval_score_cutoff=0.5, offered_rate=0.035, approved_term_months_max=24
        )

        def run_with_propensity(value: float) -> pd.DataFrame:
            monkeypatch.setattr(
                truth_module,
                "generate_latent_customer_truth",
                lambda customers, rng: pd.DataFrame(
                    {
                        "customer_id": customers["customer_id"],
                        "latent_payment_propensity": [value] * len(customers),
                    }
                ),
            )
            customers = pd.DataFrame({"customer_id": applications["customer_id"].unique()})
            # exercising truth.py itself with the monkeypatched extreme value -
            # proves the perturbation actually took effect on this axis.
            forced_truth = truth_module.generate_latent_customer_truth(
                customers, np.random.default_rng(0)
            )
            assert (forced_truth["latent_payment_propensity"] == value).all()

            decisions, _ = generate_credit_decisions(
                applications,
                features,
                "POL_test_0000001",
                policy,
                1000.0,
                5000.0,
                IdFactory("decision", "abcdef01"),
                np.random.default_rng(123),
            )
            return decisions.drop(columns=["decision_id"])

        decisions_low_propensity = run_with_propensity(0.001)
        decisions_high_propensity = run_with_propensity(0.999)

        pd.testing.assert_frame_equal(decisions_low_propensity, decisions_high_propensity)
