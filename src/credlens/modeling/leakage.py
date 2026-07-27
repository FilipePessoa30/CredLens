"""Static leakage controls (Phase 8 section 8.1) plus the building blocks
`tests/test_modeling_leakage.py` and `tests/test_modeling_negative_controls.py`
use for the functional controls (section 8.2/21).

Static controls are a hard allowlist derived from
`config/modeling/feature_registry.yml` - a column reaches the estimator
only if its `status` is `allowed` or `engineered_allowed`. The target, the
identifier, and every `excluded_sensitive`/`excluded_leakage` column raise
immediately if seen in a training frame. This module does not try to
detect leakage by column-NAME pattern matching alone (section 8: "Não
determine leakage apenas procurando nomes de colunas") - the functional
controls that actually re-fit a pipeline and measure performance live in
`credlens.modeling.training`/`tests/test_modeling_negative_controls.py`,
using the helpers below to construct the perturbed inputs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from credlens.modeling.contracts import FeatureRegistry, TargetContract


class LeakageError(Exception):
    """Raised when a training frame contains a disallowed column."""


def allowed_feature_names(registry: FeatureRegistry) -> frozenset[str]:
    return frozenset(registry.allowed_feature_names)


def restricted_column_names(registry: FeatureRegistry) -> frozenset[str]:
    return frozenset(registry.audit_only_columns)


def assert_only_allowed_features(columns: list[str], registry: FeatureRegistry) -> None:
    allowed = allowed_feature_names(registry)
    disallowed = [c for c in columns if c not in allowed]
    if disallowed:
        raise LeakageError(
            f"Column(s) not on the feature registry's allowlist: {disallowed}. "
            "Only 'allowed'/'engineered_allowed' features may enter the training frame."
        )


def assert_target_absent(columns: list[str], contract: TargetContract) -> None:
    if contract.target_column in columns:
        raise LeakageError(
            f"Target column '{contract.target_column}' must never appear in the training frame."
        )


def assert_identifier_absent(columns: list[str], contract: TargetContract) -> None:
    if contract.identifier_column in columns:
        raise LeakageError(
            f"Identifier column '{contract.identifier_column}' must never appear in the "
            "training frame."
        )


def assert_restricted_absent(columns: list[str], registry: FeatureRegistry) -> None:
    restricted = restricted_column_names(registry)
    present = [c for c in columns if c in restricted]
    if present:
        raise LeakageError(
            f"Restricted (audit-only/sensitive) column(s) present in the training frame: "
            f"{present}. These may only be used post-hoc by credlens.modeling.subgroup_audit."
        )


def assert_training_frame_is_clean(
    columns: list[str], registry: FeatureRegistry, contract: TargetContract
) -> None:
    """The single entry point `credlens.modeling.training` calls before
    fitting anything - runs every static control in one place."""
    assert_target_absent(columns, contract)
    assert_identifier_absent(columns, contract)
    assert_restricted_absent(columns, registry)
    assert_only_allowed_features(columns, registry)


# --- Functional negative-control fixtures (Phase 8 sections 8.2, 21) -----


def shuffle_target(y: pd.Series, seed: int) -> pd.Series:
    """An independent random permutation of the target, breaking any real
    relationship with the features. A pipeline trained against this
    should score close to random (ROC-AUC near 0.5)."""
    rng = np.random.default_rng(seed)
    shuffled = y.to_numpy(copy=True)
    rng.shuffle(shuffled)
    return pd.Series(shuffled, index=y.index, name=y.name)


def make_direct_target_feature(y: pd.Series) -> pd.Series:
    """A feature that IS the target, renamed - used only to prove the
    static allowlist (`assert_only_allowed_features`) rejects it; never
    actually fed to an estimator."""
    return y.rename("target_direct_copy")


def make_near_perfect_leakage_feature(
    y: pd.Series, seed: int, noise_std: float = 0.01
) -> pd.Series:
    """The target plus a small amount of Gaussian noise - almost, but not
    exactly, the target itself. A model given this column should reach
    near-perfect discrimination, demonstrating the evaluation pipeline
    CAN detect near-perfect leakage when it slips through (it is never
    added to the real allowlisted training frame)."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(loc=0.0, scale=noise_std, size=len(y))
    return pd.Series(y.to_numpy(dtype=float) + noise, index=y.index, name="near_perfect_leak")


def id_only_frame(ids: pd.Series) -> pd.DataFrame:
    """A single-column frame containing nothing but the identifier -
    used to prove a model given ONLY an ID column (relabeled as a
    generic numeric feature) performs no better than random/prior."""
    return pd.DataFrame({"id_as_feature": ids.to_numpy(dtype=float)}, index=ids.index)
