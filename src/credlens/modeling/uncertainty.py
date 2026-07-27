"""Bootstrap uncertainty and multi-seed split stability (Phase 8 section
16).

Both explicitly represent "Variabilidade entre reamostragens do conjunto
de teste deste benchmark" / run-to-run variability of THIS pipeline on
THIS benchmark - never a claim about generalization to a real
institution or population (the same posture Phase 7's
`credlens.analysis.robustness` takes for the synthetic DGP). Split
stability creates entirely FRESH splits per seed, each with its own
official test set - it never re-touches the officially registered
experiment's locked test set for tuning or selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from credlens.modeling.contracts import EvaluationConfig, FeatureRegistry, TargetContract
from credlens.modeling.evaluation import (
    brier,
    confusion_at_threshold,
    ks_statistic,
    pr_auc,
    roc_auc,
)
from credlens.modeling.features import engineer_features
from credlens.modeling.splitting import create_split
from credlens.modeling.training import ModelKind, fit_model, predict_proba_positive

VARIABILITY_LABEL_EN = (
    "Resampling variability on this benchmark's test set - not generalization "
    "to any real institution"
)
VARIABILITY_LABEL_PT_BR = (
    "Variabilidade de reamostragem no conjunto de teste deste benchmark - "
    "não é generalização para nenhuma instituição real"
)


@dataclass(frozen=True)
class BootstrapMetricResult:
    metric: str
    point_estimate: float
    mean: float
    p2_5: float
    p50: float
    p97_5: float
    n_resamples: int
    n_failures: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "point_estimate": round(self.point_estimate, 6),
            "mean": round(self.mean, 6),
            "p2_5": round(self.p2_5, 6),
            "p50": round(self.p50, 6),
            "p97_5": round(self.p97_5, 6),
            "n_resamples": self.n_resamples,
            "n_failures": self.n_failures,
        }


@dataclass(frozen=True)
class BootstrapReport:
    seed: int
    method: str
    n_resamples: int
    effective_n_test: int
    metrics: dict[str, BootstrapMetricResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "method": self.method,
            "n_resamples": self.n_resamples,
            "effective_n_test": self.effective_n_test,
            "label_en": VARIABILITY_LABEL_EN,
            "label_pt_br": VARIABILITY_LABEL_PT_BR,
            "metrics": {k: v.to_dict() for k, v in self.metrics.items()},
        }


def _stratified_resample_indices(y: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    positive_idx = np.flatnonzero(y == 1)
    negative_idx = np.flatnonzero(y == 0)
    resampled_pos = rng.choice(positive_idx, size=len(positive_idx), replace=True)
    resampled_neg = rng.choice(negative_idx, size=len(negative_idx), replace=True)
    return np.concatenate([resampled_pos, resampled_neg])


def bootstrap_test_metrics(
    y_test: pd.Series,
    p_test: pd.Series,
    *,
    top_decile_threshold: float,
    config: EvaluationConfig,
) -> BootstrapReport:
    cfg = config.uncertainty["bootstrap"]
    n_resamples = int(cfg["n_resamples"])
    seed = int(cfg["seed"])
    percentiles = cfg["percentiles"]
    rng = np.random.default_rng(seed)

    y_arr = y_test.to_numpy()
    p_arr = p_test.to_numpy()
    metric_names: list[str] = list(cfg["metrics"])
    samples: dict[str, list[float]] = {m: [] for m in metric_names}
    n_failures = 0

    for _ in range(n_resamples):
        idx = _stratified_resample_indices(y_arr, rng)
        y_s, p_s = y_arr[idx], p_arr[idx]
        try:
            if "roc_auc" in samples:
                samples["roc_auc"].append(roc_auc(pd.Series(y_s), pd.Series(p_s)))
            if "pr_auc" in samples:
                samples["pr_auc"].append(pr_auc(pd.Series(y_s), pd.Series(p_s)))
            if "brier" in samples:
                samples["brier"].append(brier(pd.Series(y_s), pd.Series(p_s)))
            if "ks" in samples:
                samples["ks"].append(ks_statistic(pd.Series(y_s), pd.Series(p_s)))
            if "recall_at_top_10_pct" in samples or "precision_at_top_10_pct" in samples:
                cm = confusion_at_threshold(pd.Series(y_s), pd.Series(p_s), top_decile_threshold)
                if "recall_at_top_10_pct" in samples:
                    samples["recall_at_top_10_pct"].append(cm.recall)
                if "precision_at_top_10_pct" in samples:
                    samples["precision_at_top_10_pct"].append(cm.precision)
        except ValueError:
            n_failures += 1

    point_estimates: dict[str, float] = {
        "roc_auc": roc_auc(y_test, p_test),
        "pr_auc": pr_auc(y_test, p_test),
        "brier": brier(y_test, p_test),
        "ks": ks_statistic(y_test, p_test),
    }
    point_cm = confusion_at_threshold(y_test, p_test, top_decile_threshold)
    point_estimates["recall_at_top_10_pct"] = point_cm.recall
    point_estimates["precision_at_top_10_pct"] = point_cm.precision

    results: dict[str, BootstrapMetricResult] = {}
    for metric, values in samples.items():
        if not values:
            continue
        arr = np.array(values)
        results[metric] = BootstrapMetricResult(
            metric=metric,
            point_estimate=point_estimates[metric],
            mean=float(arr.mean()),
            p2_5=float(np.percentile(arr, percentiles[0])),
            p50=float(np.percentile(arr, percentiles[1])),
            p97_5=float(np.percentile(arr, percentiles[2])),
            n_resamples=len(values),
            n_failures=n_failures,
        )
    return BootstrapReport(
        seed=seed,
        method=str(cfg["method"]),
        n_resamples=n_resamples,
        effective_n_test=len(y_test),
        metrics=results,
    )


@dataclass(frozen=True)
class SplitStabilityRun:
    seed: int
    n_train: int
    n_test: int
    test_prevalence: float
    roc_auc: float
    pr_auc: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "test_prevalence": round(self.test_prevalence, 6),
            "roc_auc": round(self.roc_auc, 6),
            "pr_auc": round(self.pr_auc, 6),
        }


@dataclass(frozen=True)
class SplitStabilityReport:
    model_kind: str
    runs: list[SplitStabilityRun]
    roc_auc_mean: float
    roc_auc_stdev: float
    pr_auc_mean: float
    pr_auc_stdev: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_kind": self.model_kind,
            "runs": [r.to_dict() for r in self.runs],
            "roc_auc_mean": round(self.roc_auc_mean, 6),
            "roc_auc_stdev": round(self.roc_auc_stdev, 6),
            "pr_auc_mean": round(self.pr_auc_mean, 6),
            "pr_auc_stdev": round(self.pr_auc_stdev, 6),
            "label_en": VARIABILITY_LABEL_EN,
            "label_pt_br": VARIABILITY_LABEL_PT_BR,
        }


def split_stability_sweep(
    df: pd.DataFrame,
    *,
    registry: FeatureRegistry,
    contract: TargetContract,
    config: EvaluationConfig,
    model_kind: ModelKind = "logistic_regression",
) -> SplitStabilityReport:
    """Refits `model_kind` (with its DEFAULT hyperparameters, not a fresh
    tuning sweep - this measures split-induced variance, not tuning
    variance) on a fresh 60/20/20 split for every seed in
    `config.uncertainty.split_stability.seeds`. Every seed's test set is
    its own, newly created - none of them is the officially registered
    experiment's locked test set."""
    seeds: list[int] = list(config.uncertainty["split_stability"]["seeds"])
    features = engineer_features(df)
    target = df[contract.target_column]

    runs: list[SplitStabilityRun] = []
    for seed in seeds:
        assignment = create_split(
            df,
            id_column=contract.identifier_column,
            target_column=contract.target_column,
            config=config,
            seed=seed,
        )
        x_train = features.loc[assignment.train_index]
        y_train = target.loc[assignment.train_index]
        x_test = features.loc[assignment.test_index]
        y_test = target.loc[assignment.test_index]

        fitted = fit_model(
            model_kind, x_train, y_train, registry=registry, contract=contract, seed=seed
        )
        p_test = predict_proba_positive(fitted, x_test)
        runs.append(
            SplitStabilityRun(
                seed=seed,
                n_train=len(x_train),
                n_test=len(x_test),
                test_prevalence=float(y_test.mean()),
                roc_auc=roc_auc(y_test, p_test),
                pr_auc=pr_auc(y_test, p_test),
            )
        )

    roc_aucs = np.array([r.roc_auc for r in runs])
    pr_aucs = np.array([r.pr_auc for r in runs])
    return SplitStabilityReport(
        model_kind=model_kind,
        runs=runs,
        roc_auc_mean=float(roc_aucs.mean()),
        roc_auc_stdev=float(roc_aucs.std(ddof=1)) if len(runs) > 1 else 0.0,
        pr_auc_mean=float(pr_aucs.mean()),
        pr_auc_stdev=float(pr_aucs.std(ddof=1)) if len(runs) > 1 else 0.0,
    )
