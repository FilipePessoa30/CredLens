"""Versioned allowlist of the columns credlens.generation.decisions is
allowed to read when computing a synthetic decision score (Phase 4B
section 4.3). This is an explicit interface, not just convention: any
code path in decisions.py must go through select_decision_features()
below rather than reading application_features directly, so that a
future column added to application_features (e.g. a behavioral or
future-looking field) cannot silently start influencing the score just
by existing on the table.

Versioned as a module-level constant (not read from a config file):
changing it is a code change to what a synthetic underwriting policy is
allowed to see, deliberately not something a scenario config can
override.
"""

from __future__ import annotations

import pandas as pd

ALLOWLIST_VERSION = 1

# Every column here is application_features' own frozen-at-proposal data
# (see docs/adr/0004-feature-freeze-at-proposal.md) - nothing that could
# only be known after a decision (payment behavior, DPD, write-off) and
# nothing from fairness_attributes (evaluation-only, see
# docs/adr/0005-fairness-attribute-separation.md) or the truth layer
# (see docs/adr/0007-synthetic-truth-isolation.md).
DECISION_FEATURE_ALLOWLIST: tuple[str, ...] = (
    "bureau_score_bucket",
    "declared_income",
    "debt_to_income",
)

# Columns that must NEVER appear in the allowlist above - a belt-and-braces
# check (see assert_allowlist_is_safe) against ever accidentally adding a
# behavioral, fairness, or latent-truth column to it.
_FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "propensity",
    "latent",
    "truth",
    "dpd",
    "write_off",
    "payment",
    "gender",
    "age_bracket",
    "region",
    "fairness",
)


class AllowlistError(Exception):
    """Raised when the allowlist itself, or a request to use it, is unsafe."""


def assert_allowlist_is_safe() -> None:
    for column in DECISION_FEATURE_ALLOWLIST:
        lowered = column.lower()
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            if forbidden in lowered:
                raise AllowlistError(
                    f"DECISION_FEATURE_ALLOWLIST contains '{column}', which matches the "
                    f"forbidden pattern '{forbidden}' - a behavioral/fairness/latent-truth "
                    "column must never be readable by the decision score."
                )


def select_decision_features(application_features: pd.DataFrame) -> pd.DataFrame:
    """The ONLY sanctioned way for credlens.generation.decisions to read
    application_features - returns a copy containing exactly
    DECISION_FEATURE_ALLOWLIST's columns, in allowlist order (the caller's
    own index, e.g. application_id, is preserved as-is; this function
    only restricts which COLUMNS are visible to the score). Raises if a
    required column is missing - never silently drops or fabricates one."""
    assert_allowlist_is_safe()
    missing = [c for c in DECISION_FEATURE_ALLOWLIST if c not in application_features.columns]
    if missing:
        raise AllowlistError(
            f"application_features is missing allowlisted column(s) {missing} - "
            "cannot compute a decision score."
        )
    return application_features[list(DECISION_FEATURE_ALLOWLIST)].copy()
