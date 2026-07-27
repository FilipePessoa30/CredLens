"""Perturbation stress tests (Phase 8 section 20) - TECHNICAL robustness
of the fitted pipeline under controlled input perturbations, never a
forecast of any real future crisis or population shift.

Most perturbations are applied to the RAW test frame (before feature
engineering), so they also exercise `credlens.modeling.features` under
conditions the original UCI file never has. `additional_missingness` is
the one exception: it is injected directly into the ENGINEERED feature
matrix, not the raw columns - `credlens.modeling.features.engineer_
features` was never designed to accept missing raw inputs (UCI has zero
missing values, so there was no reason to), so testing "does the
preprocessing pipeline's imputer really work" means giving the fitted
`sklearn.Pipeline` (whose first step IS the imputer) a feature frame with
real gaps, not asking the feature-engineering layer to guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from credlens.modeling.contracts import EvaluationConfig
from credlens.modeling.evaluation import (
    brier,
    calibration_intercept_slope,
    confusion_at_threshold,
    pr_auc,
)
from credlens.modeling.features import FEATURE_COLUMNS, engineer_features
from credlens.modeling.training import FittedModel, predict_proba_positive

_DELINQUENCY_COLUMNS = ["X6", "X7", "X8", "X9", "X10", "X11"]
_BILL_COLUMNS = ["X12", "X13", "X14", "X15", "X16", "X17"]
_PAYMENT_COLUMNS = ["X18", "X19", "X20", "X21", "X22", "X23"]

PERTURBATION_KINDS: tuple[str, ...] = (
    "additional_missingness",
    "outliers",
    "utilization_shift",
    "delinquency_worsening",
    "payment_shrink",
    "prevalence_drift_low",
    "prevalence_drift_high",
    "gaussian_noise",
    "out_of_domain_delinquency_code",
)


def _inject_feature_missingness(
    features: pd.DataFrame, cfg: dict[str, Any], rng: np.random.Generator
) -> pd.DataFrame:
    out = features.astype(float).copy()
    mask = rng.random(out.shape) < float(cfg["missingness_extra_fraction"])
    values = out.to_numpy()
    values[mask] = np.nan
    return pd.DataFrame(values, index=out.index, columns=out.columns)


def _perturb_outliers(
    df: pd.DataFrame, cfg: dict[str, Any], rng: np.random.Generator
) -> pd.DataFrame:
    out = df.copy()
    mask = rng.random(len(out)) < float(cfg["outlier_fraction"])
    out.loc[mask, _BILL_COLUMNS] = out.loc[mask, _BILL_COLUMNS] * float(cfg["outlier_multiplier"])
    return out


def _perturb_utilization_shift(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    out = df.copy()
    out[_BILL_COLUMNS] = out[_BILL_COLUMNS] * float(cfg["utilization_shift_multiplier"])
    return out


def _perturb_delinquency_worsening(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    out = df.copy()
    steps = int(cfg["delinquency_worsening_steps"])
    out[_DELINQUENCY_COLUMNS] = (out[_DELINQUENCY_COLUMNS] + steps).clip(lower=-2, upper=9)
    return out


def _perturb_payment_shrink(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    out = df.copy()
    out[_PAYMENT_COLUMNS] = out[_PAYMENT_COLUMNS] * float(cfg["payment_to_bill_shrink_factor"])
    return out


def _perturb_gaussian_noise(
    df: pd.DataFrame, cfg: dict[str, Any], rng: np.random.Generator
) -> pd.DataFrame:
    out = df.copy()
    fraction = float(cfg["gaussian_noise_std_fraction"])
    for col in [*_BILL_COLUMNS, *_PAYMENT_COLUMNS]:
        std = out[col].std(ddof=0)
        noise = rng.normal(loc=0.0, scale=fraction * std, size=len(out)) if std > 0 else 0.0
        out[col] = out[col] + noise
    return out


def _perturb_out_of_domain_code(
    df: pd.DataFrame, cfg: dict[str, Any], rng: np.random.Generator
) -> pd.DataFrame:
    out = df.copy()
    code = int(cfg["out_of_domain_delinquency_code"])
    mask = rng.random((len(out), len(_DELINQUENCY_COLUMNS))) < 0.05
    values = out[_DELINQUENCY_COLUMNS].to_numpy(dtype=float)
    values[mask] = code
    out[_DELINQUENCY_COLUMNS] = values
    return out


def _perturb_prevalence_drift(
    raw: pd.DataFrame, y: pd.Series, target_prevalence: float, rng: np.random.Generator
) -> tuple[pd.DataFrame, pd.Series]:
    """Subsamples the minority or majority class to hit
    `target_prevalence` - a resampling, not a relabeling; every row kept
    retains its true original label."""
    positive_idx = y.index[y == 1]
    negative_idx = y.index[y == 0]
    n_pos, n_neg = len(positive_idx), len(negative_idx)

    if target_prevalence < n_pos / (n_pos + n_neg):
        target_n_pos = round(target_prevalence * n_neg / (1 - target_prevalence))
        keep_pos = pd.Index(rng.choice(positive_idx, size=min(target_n_pos, n_pos), replace=False))
        keep_neg = negative_idx
    else:
        target_n_neg = round(n_pos * (1 - target_prevalence) / target_prevalence)
        keep_neg = pd.Index(rng.choice(negative_idx, size=min(target_n_neg, n_neg), replace=False))
        keep_pos = positive_idx

    keep_index = keep_pos.union(keep_neg)
    return raw.loc[keep_index], y.loc[keep_index]


def _build_perturbed_features(
    kind: str,
    raw_test: pd.DataFrame,
    y_test: pd.Series,
    cfg: dict[str, Any],
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.Series]:
    if kind == "additional_missingness":
        clean_features = engineer_features(raw_test)
        return _inject_feature_missingness(clean_features, cfg, rng), y_test
    if kind == "outliers":
        return engineer_features(_perturb_outliers(raw_test, cfg, rng)), y_test
    if kind == "utilization_shift":
        return engineer_features(_perturb_utilization_shift(raw_test, cfg)), y_test
    if kind == "delinquency_worsening":
        return engineer_features(_perturb_delinquency_worsening(raw_test, cfg)), y_test
    if kind == "payment_shrink":
        return engineer_features(_perturb_payment_shrink(raw_test, cfg)), y_test
    if kind == "gaussian_noise":
        return engineer_features(_perturb_gaussian_noise(raw_test, cfg, rng)), y_test
    if kind == "out_of_domain_delinquency_code":
        return engineer_features(_perturb_out_of_domain_code(raw_test, cfg, rng)), y_test
    if kind in ("prevalence_drift_low", "prevalence_drift_high"):
        targets = cfg["prevalence_drift_targets"]
        target = targets[0] if kind == "prevalence_drift_low" else targets[1]
        sub_raw, sub_y = _perturb_prevalence_drift(raw_test, y_test, float(target), rng)
        return engineer_features(sub_raw), sub_y
    raise ValueError(f"Unknown perturbation kind '{kind}'.")


@dataclass(frozen=True)
class PerturbationResult:
    kind: str
    n_rows: int
    baseline_pr_auc: float
    perturbed_pr_auc: float
    pr_auc_degradation: float
    baseline_brier: float
    perturbed_brier: float
    brier_degradation: float
    calibration_slope_shift: float
    ranking_spearman_correlation: float | None
    selection_rate_shift: float
    had_error_or_nan: bool
    error_message: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "n_rows": self.n_rows,
            "baseline_pr_auc": round(self.baseline_pr_auc, 6),
            "perturbed_pr_auc": round(self.perturbed_pr_auc, 6),
            "pr_auc_degradation": round(self.pr_auc_degradation, 6),
            "baseline_brier": round(self.baseline_brier, 6),
            "perturbed_brier": round(self.perturbed_brier, 6),
            "brier_degradation": round(self.brier_degradation, 6),
            "calibration_slope_shift": round(self.calibration_slope_shift, 6),
            "ranking_spearman_correlation": (
                round(self.ranking_spearman_correlation, 6)
                if self.ranking_spearman_correlation is not None
                else None
            ),
            "selection_rate_shift": round(self.selection_rate_shift, 6),
            "had_error_or_nan": self.had_error_or_nan,
            "error_message": self.error_message,
        }


def _evaluate_one(
    kind: str,
    fitted: FittedModel,
    raw_test: pd.DataFrame,
    y_test: pd.Series,
    baseline_p: pd.Series,
    threshold: float,
    cfg: dict[str, Any],
    rng: np.random.Generator,
) -> PerturbationResult:
    baseline_pr = pr_auc(y_test, baseline_p)
    baseline_brier_score = brier(y_test, baseline_p)
    _, baseline_slope = calibration_intercept_slope(y_test, baseline_p)
    baseline_cm = confusion_at_threshold(y_test, baseline_p, threshold)

    try:
        perturbed_features, perturbed_y = _build_perturbed_features(
            kind, raw_test, y_test, cfg, rng
        )
        perturbed_features = perturbed_features[FEATURE_COLUMNS]
        perturbed_p = predict_proba_positive(fitted, perturbed_features)
        if not np.isfinite(perturbed_p.to_numpy()).all():
            raise ValueError("Perturbed predictions contain NaN/Inf.")

        perturbed_pr = pr_auc(perturbed_y, perturbed_p)
        perturbed_brier_score = brier(perturbed_y, perturbed_p)
        _, perturbed_slope = calibration_intercept_slope(perturbed_y, perturbed_p)
        perturbed_cm = confusion_at_threshold(perturbed_y, perturbed_p, threshold)

        ranking_corr: float | None = None
        if perturbed_features.index.equals(raw_test.index):
            ranking_corr = float(spearmanr(baseline_p, perturbed_p).statistic)

        return PerturbationResult(
            kind=kind,
            n_rows=len(perturbed_features),
            baseline_pr_auc=baseline_pr,
            perturbed_pr_auc=perturbed_pr,
            pr_auc_degradation=baseline_pr - perturbed_pr,
            baseline_brier=baseline_brier_score,
            perturbed_brier=perturbed_brier_score,
            brier_degradation=perturbed_brier_score - baseline_brier_score,
            calibration_slope_shift=perturbed_slope - baseline_slope,
            ranking_spearman_correlation=ranking_corr,
            selection_rate_shift=(perturbed_cm.n_flagged / perturbed_cm.n_total)
            - (baseline_cm.n_flagged / baseline_cm.n_total),
            had_error_or_nan=False,
            error_message=None,
        )
    except (ValueError, KeyError, ZeroDivisionError) as exc:
        return PerturbationResult(
            kind=kind,
            n_rows=len(raw_test),
            baseline_pr_auc=baseline_pr,
            perturbed_pr_auc=float("nan"),
            pr_auc_degradation=float("nan"),
            baseline_brier=baseline_brier_score,
            perturbed_brier=float("nan"),
            brier_degradation=float("nan"),
            calibration_slope_shift=float("nan"),
            ranking_spearman_correlation=None,
            selection_rate_shift=float("nan"),
            had_error_or_nan=True,
            error_message=str(exc),
        )


def run_robustness_suite(
    fitted: FittedModel,
    raw_test: pd.DataFrame,
    y_test: pd.Series,
    baseline_p: pd.Series,
    *,
    threshold: float,
    config: EvaluationConfig,
) -> list[PerturbationResult]:
    cfg = config.robustness
    rng = np.random.default_rng(int(cfg["seed"]))
    return [
        _evaluate_one(kind, fitted, raw_test, y_test, baseline_p, threshold, cfg, rng)
        for kind in PERTURBATION_KINDS
    ]
