"""Feature-drift metrics (Phase 9 section 15.2) - deliberately more than
just PSI: PSI, KS, Wasserstein distance, Jensen-Shannon divergence, and
shifts in mean/median/variance/quantiles/missingness, all computed
against the monitoring REFERENCE (train+validation only, never the
locked test set used to build the batches).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.spatial.distance import jensenshannon
from scipy.stats import ks_2samp, wasserstein_distance

_PSI_EPSILON = 1e-6


def population_stability_index(
    reference_values: np.ndarray, batch_values: np.ndarray, bin_edges: Sequence[float]
) -> float:
    edges = np.array(bin_edges, dtype=float)
    ref_counts, _ = np.histogram(reference_values, bins=edges)
    batch_counts, _ = np.histogram(np.clip(batch_values, edges[0], edges[-1]), bins=edges)
    ref_pct = ref_counts / max(ref_counts.sum(), 1)
    batch_pct = batch_counts / max(batch_counts.sum(), 1)
    ref_pct = np.clip(ref_pct, _PSI_EPSILON, None)
    batch_pct = np.clip(batch_pct, _PSI_EPSILON, None)
    return float(np.sum((batch_pct - ref_pct) * np.log(batch_pct / ref_pct)))


def jensen_shannon_divergence(
    reference_values: np.ndarray, batch_values: np.ndarray, bin_edges: Sequence[float]
) -> float:
    edges = np.array(bin_edges, dtype=float)
    ref_counts, _ = np.histogram(reference_values, bins=edges)
    batch_counts, _ = np.histogram(np.clip(batch_values, edges[0], edges[-1]), bins=edges)
    ref_p = ref_counts / max(ref_counts.sum(), 1)
    batch_p = batch_counts / max(batch_counts.sum(), 1)
    distance = jensenshannon(ref_p, batch_p, base=2)
    return float(distance**2) if np.isfinite(distance) else 1.0


@dataclass(frozen=True)
class FeatureDriftResult:
    feature: str
    n_reference: int
    n_batch: int
    psi: float
    ks_statistic: float
    wasserstein_distance: float
    jensen_shannon_divergence: float
    mean_shift: float
    median_shift: float
    variance_shift: float
    missingness_delta: float
    quantile_shift: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "n_reference": self.n_reference,
            "n_batch": self.n_batch,
            "psi": round(self.psi, 6),
            "ks_statistic": round(self.ks_statistic, 6),
            "wasserstein_distance": round(self.wasserstein_distance, 6),
            "jensen_shannon_divergence": round(self.jensen_shannon_divergence, 6),
            "mean_shift": round(self.mean_shift, 6),
            "median_shift": round(self.median_shift, 6),
            "variance_shift": round(self.variance_shift, 6),
            "missingness_delta": round(self.missingness_delta, 6),
            "quantile_shift": {k: round(v, 6) for k, v in self.quantile_shift.items()},
        }


def compute_feature_drift(
    feature: str,
    reference_values: np.ndarray,
    batch_values_raw: np.ndarray,
    reference_stats: dict[str, Any],
    bin_edges: Sequence[float],
) -> FeatureDriftResult:
    missingness_batch = float(np.isnan(batch_values_raw).mean()) if len(batch_values_raw) else 0.0
    batch_values = batch_values_raw[np.isfinite(batch_values_raw)]
    if len(batch_values) == 0:
        batch_values = np.array([0.0])

    quantile_shift = {}
    for q_str, ref_value in reference_stats["quantiles"].items():
        batch_q = float(np.quantile(batch_values, float(q_str)))
        quantile_shift[q_str] = batch_q - float(ref_value)

    return FeatureDriftResult(
        feature=feature,
        n_reference=len(reference_values),
        n_batch=len(batch_values),
        psi=population_stability_index(reference_values, batch_values, bin_edges),
        ks_statistic=float(ks_2samp(reference_values, batch_values).statistic),
        wasserstein_distance=float(wasserstein_distance(reference_values, batch_values)),
        jensen_shannon_divergence=jensen_shannon_divergence(
            reference_values, batch_values, bin_edges
        ),
        mean_shift=float(batch_values.mean() - reference_stats["mean"]),
        median_shift=float(np.median(batch_values) - reference_stats["median"]),
        variance_shift=float(batch_values.var(ddof=0) - reference_stats["std"] ** 2),
        missingness_delta=missingness_batch - float(reference_stats["missingness"]),
        quantile_shift=quantile_shift,
    )
