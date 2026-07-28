"""Coefficient stability audit and classification (Phase 9 sections 7.1,
7.2) - the direct response to the Phase 8 finding that
`months_delinquent_count` (strong positive coefficient) and
`consecutive_months_delinquent` (relevant negative coefficient) likely
share information (both are derived from the same six PAY_x columns).

Stability is measured three independent ways: bootstrap resampling of
the training set, cross-validation folds, and sensitivity to the
regularization strength `C`. A feature's sign flipping across any of
these is the evidence base for downgrading its reason-code language
below "protective effect" to a purely mathematical description (section
7.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from credlens.model_validation.collinearity import CollinearityReport

CoefficientCategory = Literal[
    "stable_direction",
    "unstable_direction",
    "redundant",
    "sensitive_to_regularization",
    "low_magnitude",
    "not_interpretable_individually",
]

UNSTABLE_LANGUAGE_EN = (
    "This feature reduced the fitted model score for this record; this is not evidence of a "
    "protective causal effect."
)
UNSTABLE_LANGUAGE_PT_BR = (
    "Esta feature reduziu o score do modelo ajustado para este registro; isto não é evidência de "
    "um efeito causal protetor."
)


def _fit_logistic_get_coefficients(
    x: pd.DataFrame, y: pd.Series, *, regularization_c: float = 1.0
) -> np.ndarray:
    pipeline = make_pipeline(
        StandardScaler(), LogisticRegression(C=regularization_c, max_iter=2000)
    )
    pipeline.fit(x, y)
    estimator: LogisticRegression = pipeline.named_steps["logisticregression"]
    result: np.ndarray = estimator.coef_[0]
    return result


def bootstrap_coefficient_samples(
    x_train: pd.DataFrame, y_train: pd.Series, *, n_resamples: int, seed: int
) -> pd.DataFrame:
    """Stratified-resamples train (with replacement, preserving
    prevalence) `n_resamples` times, refitting a plain scaled logistic
    regression each time - one row of coefficients per resample."""
    rng = np.random.default_rng(seed)
    y_arr = y_train.to_numpy()
    positive_idx = np.flatnonzero(y_arr == 1)
    negative_idx = np.flatnonzero(y_arr == 0)

    rows = []
    for _ in range(n_resamples):
        resampled_pos = rng.choice(positive_idx, size=len(positive_idx), replace=True)
        resampled_neg = rng.choice(negative_idx, size=len(negative_idx), replace=True)
        idx = np.concatenate([resampled_pos, resampled_neg])
        rows.append(_fit_logistic_get_coefficients(x_train.iloc[idx], y_train.iloc[idx]))
    return pd.DataFrame(rows, columns=list(x_train.columns))


def cv_fold_coefficient_samples(
    x_train: pd.DataFrame, y_train: pd.Series, *, n_folds: int, seed: int
) -> pd.DataFrame:
    """Refits on each of `n_folds` stratified folds' TRAINING portion
    (never the held-out fold) - a second, independent view of coefficient
    stability at a much smaller sample-perturbation scale than bootstrap."""
    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=seed)
    rows = []
    for train_idx, _ in skf.split(x_train, y_train):
        rows.append(
            _fit_logistic_get_coefficients(x_train.iloc[train_idx], y_train.iloc[train_idx])
        )
    return pd.DataFrame(rows, columns=list(x_train.columns))


def regularization_sensitivity_samples(
    x_train: pd.DataFrame, y_train: pd.Series, *, c_grid: list[float]
) -> pd.DataFrame:
    rows = [_fit_logistic_get_coefficients(x_train, y_train, regularization_c=c) for c in c_grid]
    return pd.DataFrame(rows, columns=list(x_train.columns), index=pd.Index(c_grid, name="C"))


@dataclass(frozen=True)
class CoefficientClassification:
    feature: str
    original_coefficient: float
    original_odds_ratio: float
    bootstrap_sign_flip_rate: float
    cv_sign_flip_rate: float
    regularization_sign_changes: bool
    vif: float
    category: CoefficientCategory
    reason_code_language_en: str
    reason_code_language_pt_br: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "original_coefficient": round(self.original_coefficient, 6),
            "original_odds_ratio": round(self.original_odds_ratio, 6),
            "bootstrap_sign_flip_rate": round(self.bootstrap_sign_flip_rate, 4),
            "cv_sign_flip_rate": round(self.cv_sign_flip_rate, 4),
            "regularization_sign_changes": self.regularization_sign_changes,
            "vif": round(self.vif, 4) if np.isfinite(self.vif) else None,
            "category": self.category,
            "reason_code_language_en": self.reason_code_language_en,
            "reason_code_language_pt_br": self.reason_code_language_pt_br,
        }


def _sign_flip_rate(samples: pd.DataFrame, feature: str, original_sign: int) -> float:
    signs = np.sign(samples[feature].to_numpy())
    signs = np.where(signs == 0, original_sign, signs)
    return float(np.mean(signs != original_sign))


def classify_coefficients(
    original_coefficients: dict[str, float],
    bootstrap_samples: pd.DataFrame,
    cv_samples: pd.DataFrame,
    regularization_samples: pd.DataFrame,
    collinearity: CollinearityReport,
    cfg: dict[str, Any],
) -> list[CoefficientClassification]:
    unstable_threshold = float(cfg["sign_flip_rate_unstable_threshold"])
    low_band = cfg["low_magnitude_odds_ratio_band"]
    vif_action = float(cfg["vif_action_threshold"])
    vif_by_feature = {row.feature: row.vif for row in collinearity.vif_table}

    results = []
    for feature, coefficient in original_coefficients.items():
        original_sign = 1 if coefficient >= 0 else -1
        odds_ratio = float(np.exp(coefficient))
        bootstrap_flip = _sign_flip_rate(bootstrap_samples, feature, original_sign)
        cv_flip = _sign_flip_rate(cv_samples, feature, original_sign)
        reg_signs = np.sign(regularization_samples[feature].to_numpy())
        reg_signs = np.where(reg_signs == 0, original_sign, reg_signs)
        reg_changes = bool(len(set(reg_signs.tolist())) > 1)
        vif = vif_by_feature.get(feature, float("nan"))

        if bootstrap_flip > unstable_threshold:
            category: CoefficientCategory = "unstable_direction"
        elif vif >= vif_action:
            category = "redundant"
        elif reg_changes:
            category = "sensitive_to_regularization"
        elif low_band[0] <= odds_ratio <= low_band[1]:
            category = "low_magnitude"
        elif bootstrap_flip > 0.0 or cv_flip > 0.0:
            category = "not_interpretable_individually"
        else:
            category = "stable_direction"

        if category in ("unstable_direction", "redundant", "not_interpretable_individually"):
            reason_en, reason_pt = UNSTABLE_LANGUAGE_EN, UNSTABLE_LANGUAGE_PT_BR
        else:
            direction_en = "increases" if coefficient > 0 else "decreases"
            direction_pt = "aumenta" if coefficient > 0 else "diminui"
            reason_en = f"This feature consistently {direction_en} the fitted model score."
            reason_pt = f"Esta feature consistentemente {direction_pt} o score do modelo ajustado."

        results.append(
            CoefficientClassification(
                feature=feature,
                original_coefficient=coefficient,
                original_odds_ratio=odds_ratio,
                bootstrap_sign_flip_rate=bootstrap_flip,
                cv_sign_flip_rate=cv_flip,
                regularization_sign_changes=reg_changes,
                vif=vif,
                category=category,
                reason_code_language_en=reason_en,
                reason_code_language_pt_br=reason_pt,
            )
        )
    return sorted(results, key=lambda r: abs(r.original_coefficient), reverse=True)
