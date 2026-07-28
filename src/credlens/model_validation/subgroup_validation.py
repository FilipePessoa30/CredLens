"""Independent recomputation of subgroup diagnostics (Phase 9 section 9) -
audits the Phase 8 finding reported as "Gap máximo de TPR = 0.3323",
which needs to be checked because it could represent the single largest
TPR *value* observed rather than a difference between groups.

Recomputes every subgroup's confusion counts directly from raw
predictions via `credlens.model_validation.thresholds.
independent_confusion_counts` (not `credlens.modeling.evaluation.
confusion_at_threshold`) and reports gaps under TWO explicit, separately
labeled definitions (section 9.1):

  - `absolute_gap` = max(metric across reportable groups in one
    attribute) - min(metric across the same groups) - a real spread, per
    attribute, never blended across attributes into one number.
  - `reference_gap` = metric_group - metric_reference, where the
    reference group is the LARGEST-n group for that attribute (a
    majority-group baseline, declared explicitly, not implied).

Bootstrap confidence bands are computed only for `adequate` groups
(n >= 100, per `credlens.analysis.sample_policy`); `limited` groups are
flagged low-stability and never ranked; `insufficient` groups are
excluded from every gap computation, exactly like Phase 8.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from credlens.analysis.sample_policy import SampleClassification, classify_sample_size
from credlens.model_validation.calibration import independent_brier
from credlens.model_validation.discrimination import independent_pr_auc, independent_roc_auc
from credlens.model_validation.thresholds import independent_confusion_counts

_SEX_LABELS = {1: "male", 2: "female"}
_EDUCATION_LABELS = {1: "graduate_school", 2: "university", 3: "high_school", 4: "others"}
_MARRIAGE_LABELS = {1: "married", 2: "single", 3: "others"}
_UNDOCUMENTED_LABEL = "undocumented_code"


def _bucket_age(age: pd.Series, buckets: list[list[int]]) -> pd.Series:
    labels = pd.Series("out_of_range", index=age.index)
    for low, high in buckets:
        mask = (age >= low) & (age < high)
        labels[mask] = f"{low}-{high}"
    return labels


@dataclass(frozen=True)
class GroupMetricRecomputation:
    attribute: str
    group: str
    n: int
    sample_classification: SampleClassification
    prevalence: float
    true_positive_rate: float | None
    false_positive_rate: float | None
    precision: float | None
    selection_rate: float
    roc_auc: float | None
    pr_auc: float | None
    brier_score: float | None
    bootstrap: dict[str, dict[str, float]] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attribute": self.attribute,
            "group": self.group,
            "n": self.n,
            "sample_classification": self.sample_classification,
            "prevalence": round(self.prevalence, 6),
            "true_positive_rate": (
                round(self.true_positive_rate, 6) if self.true_positive_rate is not None else None
            ),
            "false_positive_rate": (
                round(self.false_positive_rate, 6) if self.false_positive_rate is not None else None
            ),
            "precision": round(self.precision, 6) if self.precision is not None else None,
            "selection_rate": round(self.selection_rate, 6),
            "roc_auc": round(self.roc_auc, 6) if self.roc_auc is not None else None,
            "pr_auc": round(self.pr_auc, 6) if self.pr_auc is not None else None,
            "brier_score": round(self.brier_score, 6) if self.brier_score is not None else None,
            "bootstrap": self.bootstrap,
        }


def _bootstrap_group_metrics(
    y: pd.Series,
    p: pd.Series,
    threshold: float,
    *,
    n_resamples: int,
    seed: int,
    percentiles: list[float],
) -> dict[str, dict[str, float]]:
    rng = np.random.default_rng(seed)
    y_arr = y.to_numpy()
    p_arr = p.to_numpy()
    n = len(y_arr)
    tpr_samples, selection_samples, roc_samples = [], [], []
    for _ in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        y_s, p_s = pd.Series(y_arr[idx]), pd.Series(p_arr[idx])
        counts = independent_confusion_counts(y_s, p_s, threshold)
        tpr_samples.append(counts.recall)
        selection_samples.append(counts.n_flagged / counts.n_total)
        if len(set(y_s.tolist())) == 2:
            roc_samples.append(independent_roc_auc(y_s, p_s))

    def _band(samples: list[float]) -> dict[str, float]:
        arr = np.array(samples)
        return {f"p{pct}": float(np.percentile(arr, pct)) for pct in percentiles}

    return {
        "true_positive_rate": _band(tpr_samples),
        "selection_rate": _band(selection_samples),
        "roc_auc": _band(roc_samples) if roc_samples else {},
    }


def _group_metric(
    attribute: str,
    group: str,
    y: pd.Series,
    p: pd.Series,
    threshold: float,
    bootstrap_cfg: dict[str, Any],
) -> GroupMetricRecomputation:
    n = len(y)
    classification = classify_sample_size(n)
    counts = independent_confusion_counts(y, p, threshold) if n > 0 else None
    can_score = n >= 2 and y.nunique() == 2

    bootstrap = None
    if classification == "adequate" and n > 0:
        bootstrap = _bootstrap_group_metrics(
            y,
            p,
            threshold,
            n_resamples=int(bootstrap_cfg["n_resamples"]),
            seed=int(bootstrap_cfg["seed"]),
            percentiles=list(bootstrap_cfg["percentiles"]),
        )

    return GroupMetricRecomputation(
        attribute=attribute,
        group=group,
        n=n,
        sample_classification=classification,
        prevalence=float(y.mean()) if n > 0 else 0.0,
        true_positive_rate=counts.recall if counts else None,
        false_positive_rate=(1.0 - counts.specificity) if counts else None,
        precision=counts.precision if counts else None,
        selection_rate=(counts.n_flagged / counts.n_total) if counts else 0.0,
        roc_auc=independent_roc_auc(y, p) if can_score else None,
        pr_auc=independent_pr_auc(y, p) if can_score else None,
        brier_score=independent_brier(y, p) if n > 0 else None,
        bootstrap=bootstrap,
    )


@dataclass(frozen=True)
class AttributeGapReport:
    attribute: str
    metric: str
    reference_group: str
    reportable_groups: list[str]
    absolute_gap: float | None
    per_group_reference_gap: dict[str, float]
    absolute_gap_including_limited: float | None
    limited_groups_excluded_from_ranking: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "attribute": self.attribute,
            "metric": self.metric,
            "reference_group": self.reference_group,
            "reportable_groups": self.reportable_groups,
            "absolute_gap": round(self.absolute_gap, 6) if self.absolute_gap is not None else None,
            "per_group_reference_gap": {
                k: round(v, 6) for k, v in self.per_group_reference_gap.items()
            },
            "absolute_gap_including_limited": (
                round(self.absolute_gap_including_limited, 6)
                if self.absolute_gap_including_limited is not None
                else None
            ),
            "limited_groups_excluded_from_ranking": self.limited_groups_excluded_from_ranking,
        }


def _compute_gap_reports(
    metrics: list[GroupMetricRecomputation], attribute: str, metric_name: str
) -> AttributeGapReport | None:
    """Only `adequate` groups (Phase 9 section 9.2: "Para grupos
    limitados: ... não gere ranking") feed the headline `absolute_gap`/
    `per_group_reference_gap` - `limited` groups are never used for
    ranking, only shown descriptively via
    `absolute_gap_including_limited` so the correction this makes is
    itself visible, not silently applied."""
    attribute_metrics = [m for m in metrics if m.attribute == attribute]
    adequate = [m for m in attribute_metrics if m.sample_classification == "adequate"]
    reportable_incl_limited = [
        m for m in attribute_metrics if m.sample_classification != "insufficient"
    ]

    values = {
        m.group: getattr(m, metric_name) for m in adequate if getattr(m, metric_name) is not None
    }
    if len(values) < 2:
        return None
    reference_group = max(adequate, key=lambda m: m.n).group
    if reference_group not in values:
        return None
    reference_value = values[reference_group]
    absolute_gap = max(values.values()) - min(values.values())
    reference_gaps = {g: v - reference_value for g, v in values.items()}

    values_incl_limited = {
        m.group: getattr(m, metric_name)
        for m in reportable_incl_limited
        if getattr(m, metric_name) is not None
    }
    absolute_gap_incl_limited = (
        max(values_incl_limited.values()) - min(values_incl_limited.values())
        if len(values_incl_limited) >= 2
        else None
    )
    limited_excluded = sorted(
        m.group for m in attribute_metrics if m.sample_classification == "limited"
    )

    return AttributeGapReport(
        attribute=attribute,
        metric=metric_name,
        reference_group=reference_group,
        reportable_groups=sorted(values.keys()),
        absolute_gap=absolute_gap,
        per_group_reference_gap=reference_gaps,
        absolute_gap_including_limited=absolute_gap_incl_limited,
        limited_groups_excluded_from_ranking=limited_excluded,
    )


@dataclass(frozen=True)
class SubgroupValidationReport:
    threshold: float
    metrics: list[GroupMetricRecomputation]
    gap_reports: list[AttributeGapReport]
    excluded_insufficient_groups: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "threshold": round(self.threshold, 6),
            "metrics": [m.to_dict() for m in self.metrics],
            "gap_reports": [g.to_dict() for g in self.gap_reports],
            "excluded_insufficient_groups": self.excluded_insufficient_groups,
            "caveats_en": [
                "absolute_gap = max(metric) - min(metric) across reportable groups WITHIN one "
                "attribute - never blended across attributes.",
                "reference_gap = metric_group - metric_reference, where the reference group is "
                "the largest-n group for that attribute.",
                "No threshold was adjusted per group - one fixed threshold is used throughout.",
                "Not a fairness certification, not a causal-discrimination finding, not a legal/"
                "regulatory compliance assessment.",
            ],
        }


def run_subgroup_validation(
    raw_df: pd.DataFrame,
    y_test: pd.Series,
    p_test: pd.Series,
    *,
    threshold: float,
    age_buckets: list[list[int]],
    bootstrap_cfg: dict[str, Any],
) -> SubgroupValidationReport:
    group_specs: list[tuple[str, pd.Series]] = [
        ("sex", raw_df.loc[y_test.index, "X2"].map(_SEX_LABELS).fillna(_UNDOCUMENTED_LABEL)),
        (
            "education",
            raw_df.loc[y_test.index, "X3"].map(_EDUCATION_LABELS).fillna(_UNDOCUMENTED_LABEL),
        ),
        (
            "marriage",
            raw_df.loc[y_test.index, "X4"].map(_MARRIAGE_LABELS).fillna(_UNDOCUMENTED_LABEL),
        ),
        ("age_bucket", _bucket_age(raw_df.loc[y_test.index, "X5"], age_buckets)),
    ]

    metrics: list[GroupMetricRecomputation] = []
    for attribute, group_series in group_specs:
        for group_value in sorted(group_series.unique()):
            mask = (group_series == group_value).to_numpy()
            metrics.append(
                _group_metric(
                    attribute,
                    str(group_value),
                    y_test[mask],
                    p_test[mask],
                    threshold,
                    bootstrap_cfg,
                )
            )

    excluded = [
        f"{m.attribute}={m.group}" for m in metrics if m.sample_classification == "insufficient"
    ]

    gap_reports = []
    for attribute, _ in group_specs:
        for metric_name in ("true_positive_rate", "selection_rate", "roc_auc"):
            report = _compute_gap_reports(metrics, attribute, metric_name)
            if report is not None:
                gap_reports.append(report)

    return SubgroupValidationReport(
        threshold=threshold,
        metrics=metrics,
        gap_reports=gap_reports,
        excluded_insufficient_groups=excluded,
    )
