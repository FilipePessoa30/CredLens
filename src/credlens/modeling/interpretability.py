"""Global, feature-response, and local interpretability (Phase 8 section
18). SHAP is deliberately NOT used - see the module docstring below for
why - permutation importance and partial dependence (both already in
scikit-learn, no new dependency) stand in for it, as Phase 8 section 18.4
explicitly allows: "Se não for usada: documente a razão... não finja que
SHAP foi executado."

Reason codes for a decision reached in `credlens.modeling.reporting`
model cards/technical reports NEVER reference a sensitive attribute
(SEX/EDUCATION/MARRIAGE/AGE) - they cannot, structurally, since those
columns never reach the estimator in the first place (see
`credlens.modeling.leakage`). IDs shown alongside a local explanation are
always pseudonymized, never the raw UCI `ID`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.inspection import partial_dependence, permutation_importance
from sklearn.pipeline import Pipeline

from credlens.modeling.features import FEATURE_COLUMNS
from credlens.modeling.reason_code_policy import (
    ReasonCodePolicyError,
    filter_and_rank_for_reason_codes,
    load_reason_code_policy,
)
from credlens.modeling.training import FittedModel

SHAP_NOT_USED_REASON_EN = (
    "SHAP was deliberately not added as a dependency for this phase - "
    "permutation importance and partial dependence (both already in "
    "scikit-learn) cover the same global/feature-response interpretability "
    "need without introducing a large, fast-moving dependency with a "
    "narrower support matrix. See reports/modeling/technical_report.md."
)
SHAP_NOT_USED_REASON_PT_BR = (
    "O SHAP foi deliberadamente não incluído como dependência nesta fase - "
    "permutation importance e partial dependence (ambos já presentes no "
    "scikit-learn) cobrem a mesma necessidade de interpretabilidade "
    "global/de resposta de feature sem introduzir uma dependência grande "
    "e de suporte mais restrito."
)

_TOP_K_PDP_FEATURES = 5
_PERMUTATION_N_REPEATS = 20
_PERMUTATION_SEED = 42


def pseudonymize_id(raw_id: object) -> str:
    digest = hashlib.sha256(str(raw_id).encode("utf-8")).hexdigest()[:10]
    return f"CASE-{digest}"


@dataclass(frozen=True)
class CoefficientRow:
    feature: str
    coefficient: float
    odds_ratio: float
    direction: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "coefficient": round(self.coefficient, 6),
            "odds_ratio": round(self.odds_ratio, 6),
            "direction": self.direction,
        }


def logistic_coefficients(fitted: FittedModel) -> list[CoefficientRow]:
    """Coefficients in the STANDARDIZED feature space (the pipeline's own
    `StandardScaler` step) - "per one standard deviation change", the
    only unit that is directly comparable across features with different
    natural scales."""
    if fitted.model_kind != "logistic_regression":
        raise ValueError("logistic_coefficients only applies to model_kind='logistic_regression'.")
    estimator = fitted.pipeline.named_steps["estimator"]
    coefs = estimator.coef_[0]
    rows = []
    for feature, coef in zip(fitted.feature_columns, coefs, strict=True):
        rows.append(
            CoefficientRow(
                feature=feature,
                coefficient=float(coef),
                odds_ratio=float(np.exp(coef)),
                direction="increases_risk" if coef > 0 else "decreases_risk",
            )
        )
    return sorted(rows, key=lambda r: abs(r.coefficient), reverse=True)


@dataclass(frozen=True)
class PermutationImportanceRow:
    feature: str
    mean_importance: float
    stdev_importance: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "mean_importance": round(self.mean_importance, 6),
            "stdev_importance": round(self.stdev_importance, 6),
        }


def compute_permutation_importance(
    fitted: FittedModel, x: pd.DataFrame, y: pd.Series, *, scoring: str = "average_precision"
) -> list[PermutationImportanceRow]:
    """Computed on the VALIDATION set (never train - would be optimistic;
    never the locked test set - interpretability is not part of final
    test evaluation, so it never touches it either, keeping the same
    "test only evaluated once, at the end" discipline as everything
    else)."""
    result = permutation_importance(
        fitted.pipeline,
        x,
        y,
        n_repeats=_PERMUTATION_N_REPEATS,
        random_state=_PERMUTATION_SEED,
        scoring=scoring,
    )
    rows = [
        PermutationImportanceRow(
            feature=feature, mean_importance=float(mean), stdev_importance=float(std)
        )
        for feature, mean, std in zip(
            x.columns, result.importances_mean, result.importances_std, strict=True
        )
    ]
    return sorted(rows, key=lambda r: r.mean_importance, reverse=True)


@dataclass(frozen=True)
class PartialDependenceCurve:
    feature: str
    grid_values: list[float]
    average_prediction: list[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "grid_values": [round(v, 6) for v in self.grid_values],
            "average_prediction": [round(v, 6) for v in self.average_prediction],
        }


def compute_partial_dependence(
    fitted: FittedModel,
    x: pd.DataFrame,
    top_features: list[str],
    *,
    top_k: int = _TOP_K_PDP_FEATURES,
) -> list[PartialDependenceCurve]:
    """Marginal-effect curves (association, never causation - Phase 8
    section 18.2 explicitly warns against reading these as causal) for
    the `top_k` features by permutation importance."""
    curves = []
    for feature in top_features[:top_k]:
        pdp = partial_dependence(
            fitted.pipeline, x, features=[feature], kind="average", grid_resolution=20
        )
        curves.append(
            PartialDependenceCurve(
                feature=feature,
                grid_values=[float(v) for v in pdp["grid_values"][0]],
                average_prediction=[float(v) for v in pdp["average"][0]],
            )
        )
    return curves


@dataclass(frozen=True)
class ReasonCode:
    feature: str
    contribution: float
    direction: str
    tier: str = "ungoverned"
    caveat_en: str | None = None
    caveat_pt_br: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "contribution": round(self.contribution, 6),
            "direction": self.direction,
            "tier": self.tier,
            "caveat_en": self.caveat_en,
            "caveat_pt_br": self.caveat_pt_br,
        }


@dataclass(frozen=True)
class LocalExplanation:
    case_label: str
    pseudonymous_id: str
    predicted_probability: float
    actual_label: int | None
    reason_codes: list[ReasonCode]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_label": self.case_label,
            "pseudonymous_id": self.pseudonymous_id,
            "predicted_probability": round(self.predicted_probability, 6),
            "actual_label": self.actual_label,
            "reason_codes": [r.to_dict() for r in self.reason_codes],
            "note_en": (
                "Descriptive only - never a regulatory reason-code and never used for an "
                "automated decision."
            ),
            "note_pt_br": (
                "Apenas descritivo - nunca um reason code regulatório, nunca usado para "
                "decisão automatizada."
            ),
        }


def _reason_codes_from_pairs(
    contribution_pairs: list[tuple[str, float]], top_k: int, *, repo_root: Path | None
) -> list[ReasonCode]:
    """Phase 10 gate E: applies `config/model_validation/reason_codes.yml`
    before ranking - `prohibited`/`ungoverned` features are dropped, never
    ranked, never back-filled. Falls back to the unfiltered ranking only
    when no policy file is present on disk (e.g. an isolated test repo
    that only copies `config/modeling/`) - the real repo always has the
    policy, so this never silently disables enforcement there."""
    try:
        policy = load_reason_code_policy(repo_root)
    except ReasonCodePolicyError:
        ranked = sorted(contribution_pairs, key=lambda pair: abs(pair[1]), reverse=True)[:top_k]
        return [
            ReasonCode(
                feature=feature,
                contribution=value,
                direction="increases_risk" if value > 0 else "decreases_risk",
            )
            for feature, value in ranked
        ]

    filtered = filter_and_rank_for_reason_codes(contribution_pairs, policy, top_k=top_k)
    return [
        ReasonCode(
            feature=feature,
            contribution=value,
            direction="increases_risk" if value > 0 else "decreases_risk",
            tier=tier,
            caveat_en=policy.caveat(feature, "en"),
            caveat_pt_br=policy.caveat(feature, "pt-BR"),
        )
        for feature, value, tier in filtered
    ]


def _logistic_reason_codes(
    fitted: FittedModel, row: pd.DataFrame, top_k: int = 3, *, repo_root: Path | None = None
) -> list[ReasonCode]:
    """contribution_i = coefficient_i * standardized_value_i - the exact
    per-feature additive term inside the logistic model's own linear
    score, so this is a literal decomposition, not an approximation."""
    preprocessing: Pipeline = fitted.pipeline.named_steps["preprocessing"]
    estimator = fitted.pipeline.named_steps["estimator"]
    standardized = preprocessing.transform(row)
    standardized_arr = (
        standardized.to_numpy() if hasattr(standardized, "to_numpy") else standardized
    )
    contributions = standardized_arr[0] * estimator.coef_[0]
    pairs = [
        (feature, float(value))
        for feature, value in zip(fitted.feature_columns, contributions, strict=True)
    ]
    return _reason_codes_from_pairs(pairs, top_k, repo_root=repo_root)


def local_explanation(
    fitted: FittedModel,
    x_row: pd.DataFrame,
    raw_id: object,
    predicted_probability: float,
    actual_label: int | None,
    case_label: str,
    *,
    repo_root: Path | None = None,
) -> LocalExplanation:
    if fitted.model_kind == "logistic_regression":
        reason_codes = _logistic_reason_codes(fitted, x_row, repo_root=repo_root)
    else:
        # Non-linear challenger: fall back to a permutation-free,
        # feature-value-only ranking (raw value, not a magnitude ranking)
        # within this single row - still descriptive only, never claimed
        # as an exact decomposition the way the logistic case is. Still
        # governed by the same reason-code policy (never HistGBM
        # surfacing a prohibited feature either).
        pairs = [(col, float(x_row[col].iloc[0])) for col in FEATURE_COLUMNS]
        reason_codes = _reason_codes_from_pairs(pairs, 3, repo_root=repo_root)
        reason_codes = [
            ReasonCode(
                feature=r.feature,
                contribution=r.contribution,
                direction="see_value",
                tier=r.tier,
                caveat_en=r.caveat_en,
                caveat_pt_br=r.caveat_pt_br,
            )
            for r in reason_codes
        ]
    return LocalExplanation(
        case_label=case_label,
        pseudonymous_id=pseudonymize_id(raw_id),
        predicted_probability=predicted_probability,
        actual_label=actual_label,
        reason_codes=reason_codes,
    )


def select_representative_cases(
    y: pd.Series, p: pd.Series, ids: pd.Series, threshold: float
) -> dict[str, int]:
    """Row-index (positional into `y`/`p`/`ids`, all assumed aligned)
    selection for the 7 representative cases Phase 8 section 18.3
    requires. Returns an index INTO the original frame (not positional
    into a resorted copy)."""
    y_arr = y.to_numpy()
    p_arr = p.to_numpy()
    flagged = p_arr >= threshold

    def _pick(mask: np.ndarray, by_highest: bool) -> int | None:
        candidates = np.flatnonzero(mask)
        if len(candidates) == 0:
            return None
        ordered = candidates[np.argsort(p_arr[candidates])]
        return int(ordered[-1] if by_highest else ordered[0])

    selections: dict[str, int | None] = {
        "true_positive": _pick((y_arr == 1) & flagged, by_highest=True),
        "true_negative": _pick((y_arr == 0) & ~flagged, by_highest=False),
        "false_positive": _pick((y_arr == 0) & flagged, by_highest=True),
        "false_negative": _pick((y_arr == 1) & ~flagged, by_highest=True),
        "high_risk": _pick(np.ones_like(y_arr, dtype=bool), by_highest=True),
        "low_risk": _pick(np.ones_like(y_arr, dtype=bool), by_highest=False),
    }
    median_idx = int(np.argsort(p_arr)[len(p_arr) // 2])
    selections["intermediate_risk"] = median_idx
    return {k: v for k, v in selections.items() if v is not None}
