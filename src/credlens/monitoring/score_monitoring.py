"""Score-drift metrics (Phase 9 section 15.3) - mean/quantile shift, PSI
of the score itself, risk-band distribution shift, population above the
Phase 8 illustrative operating points, and (when the batch preserves the
same rows as an unperturbed twin) rank stability via Spearman
correlation - the same diagnostic `credlens.modeling.robustness` uses,
applied here to a monitoring batch instead of a stress-test perturbation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.stats import spearmanr

from credlens.monitoring.drift import jensen_shannon_divergence, population_stability_index


@dataclass(frozen=True)
class ScoreDriftResult:
    n_reference: int
    n_batch: int
    reference_mean_score: float
    batch_mean_score: float
    mean_shift: float
    score_psi: float
    score_quantile_shift: dict[str, float]
    risk_band_distribution: dict[str, float]
    risk_band_shift: dict[str, float]
    population_above_top10_threshold: float
    reference_population_above_top10_threshold: float
    rank_stability_spearman: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_reference": self.n_reference,
            "n_batch": self.n_batch,
            "reference_mean_score": round(self.reference_mean_score, 6),
            "batch_mean_score": round(self.batch_mean_score, 6),
            "mean_shift": round(self.mean_shift, 6),
            "score_psi": round(self.score_psi, 6),
            "score_quantile_shift": {k: round(v, 6) for k, v in self.score_quantile_shift.items()},
            "risk_band_distribution": {
                k: round(v, 6) for k, v in self.risk_band_distribution.items()
            },
            "risk_band_shift": {k: round(v, 6) for k, v in self.risk_band_shift.items()},
            "population_above_top10_threshold": round(self.population_above_top10_threshold, 6),
            "reference_population_above_top10_threshold": round(
                self.reference_population_above_top10_threshold, 6
            ),
            "rank_stability_spearman": (
                round(self.rank_stability_spearman, 6)
                if self.rank_stability_spearman is not None
                else None
            ),
        }


def _risk_band(probability: float, cuts: list[float]) -> str:
    names = ("low", "medium", "high", "very_high")
    for cut, name in zip(cuts, names[:-1], strict=True):
        if probability <= cut:
            return name
    return names[-1]


def compute_score_drift(
    reference_scores: np.ndarray,
    batch_scores: np.ndarray,
    *,
    reference_score_stats: dict[str, Any],
    risk_band_cuts: list[float],
    reference_risk_band_distribution: dict[str, float],
    top10_threshold: float,
    baseline_scores_same_rows: np.ndarray | None = None,
) -> ScoreDriftResult:
    bin_edges = reference_score_stats["histogram"]["bin_edges"]
    quantile_shift = {
        q_str: float(np.quantile(batch_scores, float(q_str))) - float(ref_value)
        for q_str, ref_value in reference_score_stats["quantiles"].items()
    }
    bands = [_risk_band(float(p), risk_band_cuts) for p in batch_scores]
    band_counts = np.unique(bands, return_counts=True)
    batch_distribution = {str(b): float(c) / len(bands) for b, c in zip(*band_counts, strict=True)}
    all_bands = ("low", "medium", "high", "very_high")
    risk_band_shift = {
        b: batch_distribution.get(b, 0.0) - float(reference_risk_band_distribution.get(b, 0.0))
        for b in all_bands
    }

    rank_stability = None
    if baseline_scores_same_rows is not None and len(baseline_scores_same_rows) == len(
        batch_scores
    ):
        rank_stability = float(spearmanr(baseline_scores_same_rows, batch_scores).statistic)

    _ = jensen_shannon_divergence  # available for callers wanting a score JS divergence too

    return ScoreDriftResult(
        n_reference=len(reference_scores),
        n_batch=len(batch_scores),
        reference_mean_score=float(reference_score_stats["mean"]),
        batch_mean_score=float(batch_scores.mean()),
        mean_shift=float(batch_scores.mean() - reference_score_stats["mean"]),
        score_psi=population_stability_index(reference_scores, batch_scores, bin_edges),
        score_quantile_shift=quantile_shift,
        risk_band_distribution=batch_distribution,
        risk_band_shift=risk_band_shift,
        population_above_top10_threshold=float(np.mean(batch_scores >= top10_threshold)),
        reference_population_above_top10_threshold=float(
            np.mean(reference_scores >= top10_threshold)
        ),
        rank_stability_spearman=rank_stability,
    )
