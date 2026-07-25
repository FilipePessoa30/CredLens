"""Synthetic decision score and credit_decisions generation.

The decision score is computed ONLY from application_features (visible,
frozen-at-proposal data) - it never reads the synthetic-truth layer
(docs/adr/0007). This is a deliberate separation: the "true" latent risk
used later to drive payment behavior (see truth.py) is not the same
number a real credit engine could ever see at decision time, and the
generator itself must not cheat by letting the policy see the future.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from credlens.generation.config import PolicyConfig
from credlens.generation.ids import IdFactory

_BUREAU_SCORE_MAP = {"thin_file": 0.40, "low": 0.30, "medium": 0.60, "high": 0.85}


def compute_decision_score(
    application_features: pd.DataFrame,
    income_min: float,
    income_max: float,
    rng: np.random.Generator,
) -> pd.Series:
    """A simple, documented, entirely synthetic scoring formula - not a
    claimed real underwriting model. Combines bureau bucket, normalized
    declared income, and debt-to-income (missing DTI treated as neutral),
    plus a small noise term so the outcome isn't a pure deterministic
    function of the visible features."""
    bureau_score = application_features["bureau_score_bucket"].map(_BUREAU_SCORE_MAP)
    income_range = max(income_max - income_min, 1e-9)
    income_score = ((application_features["declared_income"] - income_min) / income_range).clip(
        0, 1
    )
    dti = application_features["debt_to_income"]
    dti_score = (1 - (dti.fillna(0.5) / 1.5).clip(0, 1)).clip(0, 1)

    noise = rng.normal(0, 0.05, size=len(application_features))
    score = 0.45 * bureau_score + 0.30 * income_score + 0.25 * dti_score + noise
    return score.clip(0, 1)


def generate_credit_decisions(
    applications: pd.DataFrame,
    application_features: pd.DataFrame,
    policy_version_id: str,
    policy_cfg: PolicyConfig,
    income_min: float,
    income_max: float,
    decision_ids: IdFactory,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (credit_decisions, applications_with_finalized_status).

    Cancelled applications never receive a decision row - matches
    docs/state_machines.md (cancellation happens before a decision, by
    construction of this generator's own application lifecycle)."""
    decidable = applications[applications["status"] != "cancelled"].copy()
    feats = application_features.set_index("application_id").loc[decidable["application_id"]]

    score = compute_decision_score(feats.reset_index(drop=True), income_min, income_max, rng)
    approved = (score >= policy_cfg.approval_score_cutoff).to_numpy()

    submitted_at = pd.to_datetime(decidable["submitted_at"], utc=True).to_numpy()
    decision_offset_days = rng.integers(0, 4, size=len(decidable))
    decision_offset_seconds = rng.integers(0, 86400, size=len(decidable))
    decision_timestamp = (
        pd.to_datetime(submitted_at)
        + pd.to_timedelta(decision_offset_days, unit="D")
        + pd.to_timedelta(decision_offset_seconds, unit="s")
    )

    n = len(decidable)
    approved_amount = np.where(approved, decidable["requested_amount"].to_numpy(), np.nan)
    approved_term_months = np.where(
        approved,
        np.minimum(
            decidable["requested_term_months"].to_numpy(), policy_cfg.approved_term_months_max
        ),
        np.nan,
    )
    offered_rate = np.where(approved, policy_cfg.offered_rate, np.nan)
    reason_code = [None if is_approved else "score_below_cutoff" for is_approved in approved]

    decision_ids_list = [decision_ids.next() for _ in range(n)]

    credit_decisions = pd.DataFrame(
        {
            "decision_id": decision_ids_list,
            "application_id": decidable["application_id"].to_numpy(),
            "policy_version_id": policy_version_id,
            "decision_timestamp": pd.DatetimeIndex(decision_timestamp).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "outcome": np.where(approved, "approved", "rejected"),
            "reason_code": reason_code,
            "approved_amount": approved_amount,
            "approved_term_months": approved_term_months,
            "offered_rate": offered_rate,
            "is_final": True,
            "logic_version": "baseline-decision-v1",
        }
    )

    finalized_status = pd.Series("rejected", index=decidable.index)
    finalized_status[approved] = "approved"
    result_applications = applications.copy()
    result_applications.loc[decidable.index, "status"] = finalized_status

    return credit_decisions, result_applications
