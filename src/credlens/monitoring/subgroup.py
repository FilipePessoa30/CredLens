"""Subgroup monitoring (Phase 9 section 15.5) - per-batch sample size,
composition shift versus the reference, score distribution, selection
rate, and (when labels are available) performance, always run through
`credlens.analysis.sample_policy` classification. Restricted attributes
never enter the model itself (Phase 8's `credlens.modeling.leakage`
already guarantees that structurally) - they are joined here purely for
post-hoc, descriptive monitoring, exactly like
`credlens.model_validation.subgroup_validation`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from credlens.analysis.sample_policy import SampleClassification, classify_sample_size
from credlens.model_validation.thresholds import independent_confusion_counts


@dataclass(frozen=True)
class SubgroupMonitoringResult:
    attribute: str
    group: str
    n: int
    sample_classification: SampleClassification
    composition_share: float
    reference_composition_share: float
    composition_shift: float
    selection_rate: float
    mean_score: float
    recall: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attribute": self.attribute,
            "group": self.group,
            "n": self.n,
            "sample_classification": self.sample_classification,
            "composition_share": round(self.composition_share, 6),
            "reference_composition_share": round(self.reference_composition_share, 6),
            "composition_shift": round(self.composition_shift, 6),
            "selection_rate": round(self.selection_rate, 6),
            "mean_score": round(self.mean_score, 6),
            "recall": round(self.recall, 6) if self.recall is not None else None,
        }


def compute_subgroup_monitoring(
    batch_df: pd.DataFrame,
    scores: np.ndarray,
    *,
    threshold: float,
    reference_composition: dict[str, dict[str, int]],
    y_batch: pd.Series | None,
) -> list[SubgroupMonitoringResult]:
    results = []
    for attribute in ("sex", "education", "marriage"):
        if attribute not in batch_df.columns:
            continue
        groups = batch_df[attribute]
        reference_counts = reference_composition.get(attribute, {})
        reference_total = sum(reference_counts.values()) or 1
        for group_value in sorted(groups.unique()):
            mask = (groups == group_value).to_numpy()
            n = int(mask.sum())
            group_scores = scores[mask]
            selection_rate = float(np.mean(group_scores >= threshold)) if n > 0 else 0.0
            recall = None
            if y_batch is not None and n > 0:
                y_group = y_batch.to_numpy()[mask]
                if len(set(y_group.tolist())) == 2 or (y_group == 1).any():
                    counts = independent_confusion_counts(
                        pd.Series(y_group), pd.Series(group_scores), threshold
                    )
                    recall = counts.recall
            results.append(
                SubgroupMonitoringResult(
                    attribute=attribute,
                    group=str(group_value),
                    n=n,
                    sample_classification=classify_sample_size(n),
                    composition_share=n / len(batch_df) if len(batch_df) else 0.0,
                    reference_composition_share=reference_counts.get(str(group_value), 0)
                    / reference_total,
                    composition_shift=(n / len(batch_df) if len(batch_df) else 0.0)
                    - reference_counts.get(str(group_value), 0) / reference_total,
                    selection_rate=selection_rate,
                    mean_score=float(group_scores.mean()) if n > 0 else 0.0,
                    recall=recall,
                )
            )
    return results
