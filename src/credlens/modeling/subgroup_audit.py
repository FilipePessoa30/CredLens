"""Post-hoc subgroup diagnostics (Phase 8 section 19) - "Fairness and
subgroup diagnostics - not a compliance assessment".

Sensitive attributes (SEX/EDUCATION/MARRIAGE/AGE) are joined to
predictions ONLY here, by row index, strictly AFTER scoring - they never
reach `credlens.modeling.training.fit_model` (enforced structurally by
`credlens.modeling.leakage`). The threshold used for selection-rate/TPR/
FPR is the SAME single threshold for every group - this module has no
code path that could set a different one per group.

Reuses Phase 7's minimum-sample policy
(`credlens.analysis.sample_policy`) rather than re-declaring its own
30/100 cutoff.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from credlens.analysis.sample_policy import SampleClassification, classify_sample_size
from credlens.modeling.evaluation import brier, confusion_at_threshold, pr_auc, roc_auc

FAIRNESS_SECTION_LABEL_EN = "Fairness and subgroup diagnostics - not a compliance assessment"
FAIRNESS_SECTION_LABEL_PT_BR = (
    "Diagnósticos de equidade e subgrupo - não é uma avaliação de conformidade"
)

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
class SubgroupMetric:
    attribute: str
    group: str
    n: int
    sample_classification: SampleClassification
    prevalence: float
    roc_auc: float | None
    pr_auc: float | None
    brier_score: float | None
    true_positive_rate: float | None
    false_positive_rate: float | None
    precision: float | None
    selection_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "attribute": self.attribute,
            "group": self.group,
            "n": self.n,
            "sample_classification": self.sample_classification,
            "prevalence": round(self.prevalence, 6),
            "roc_auc": round(self.roc_auc, 6) if self.roc_auc is not None else None,
            "pr_auc": round(self.pr_auc, 6) if self.pr_auc is not None else None,
            "brier_score": round(self.brier_score, 6) if self.brier_score is not None else None,
            "true_positive_rate": (
                round(self.true_positive_rate, 6) if self.true_positive_rate is not None else None
            ),
            "false_positive_rate": (
                round(self.false_positive_rate, 6) if self.false_positive_rate is not None else None
            ),
            "precision": round(self.precision, 6) if self.precision is not None else None,
            "selection_rate": round(self.selection_rate, 6),
        }


@dataclass(frozen=True)
class SubgroupAuditReport:
    threshold: float
    metrics: list[SubgroupMetric]
    max_selection_rate_gap: float | None
    max_tpr_gap: float | None
    excluded_insufficient_groups: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "label_en": FAIRNESS_SECTION_LABEL_EN,
            "label_pt_br": FAIRNESS_SECTION_LABEL_PT_BR,
            "threshold": round(self.threshold, 6),
            "metrics": [m.to_dict() for m in self.metrics],
            "max_selection_rate_gap": (
                round(self.max_selection_rate_gap, 6)
                if self.max_selection_rate_gap is not None
                else None
            ),
            "max_tpr_gap": round(self.max_tpr_gap, 6) if self.max_tpr_gap is not None else None,
            "excluded_insufficient_groups": self.excluded_insufficient_groups,
            "caveats_en": [
                "No threshold was adjusted per group - one fixed threshold is used throughout.",
                "This is not a fairness certification, not a causal-discrimination finding, and "
                "not a legal/regulatory compliance assessment.",
                "uci-default-credit describes Taiwan, 2005 - findings are not evidence about any "
                "other population.",
            ],
        }


def _group_metric(
    attribute: str, group: str, y: pd.Series, p: pd.Series, threshold: float
) -> SubgroupMetric:
    n = len(y)
    classification = classify_sample_size(n)
    can_score = n >= 2 and y.nunique() == 2
    cm = confusion_at_threshold(y, p, threshold)
    return SubgroupMetric(
        attribute=attribute,
        group=group,
        n=n,
        sample_classification=classification,
        prevalence=float(y.mean()) if n > 0 else 0.0,
        roc_auc=roc_auc(y, p) if can_score else None,
        pr_auc=pr_auc(y, p) if can_score else None,
        brier_score=brier(y, p) if n > 0 else None,
        true_positive_rate=cm.recall if n > 0 else None,
        false_positive_rate=(1.0 - cm.specificity) if n > 0 else None,
        precision=cm.precision if n > 0 else None,
        selection_rate=cm.n_flagged / n if n > 0 else 0.0,
    )


def run_subgroup_audit(
    raw_df: pd.DataFrame,
    y_test: pd.Series,
    p_test: pd.Series,
    *,
    threshold: float,
    age_buckets: list[list[int]],
) -> SubgroupAuditReport:
    """`raw_df` must be the RAW (unfiltered, un-engineered) UCI frame,
    indexed identically to `y_test`/`p_test` - the columns X2/X3/X4/X5 are
    read from it here, and ONLY here, never inside training."""
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

    metrics: list[SubgroupMetric] = []
    for attribute, group_series in group_specs:
        for group_value in sorted(group_series.unique()):
            mask = (group_series == group_value).to_numpy()
            metrics.append(
                _group_metric(attribute, str(group_value), y_test[mask], p_test[mask], threshold)
            )

    reportable = [m for m in metrics if m.sample_classification != "insufficient"]
    excluded = [
        f"{m.attribute}={m.group}" for m in metrics if m.sample_classification == "insufficient"
    ]

    max_selection_gap = None
    max_tpr_gap = None
    for attribute, _ in group_specs:
        attribute_metrics = [m for m in reportable if m.attribute == attribute]
        if len(attribute_metrics) >= 2:
            selection_rates = [m.selection_rate for m in attribute_metrics]
            gap = max(selection_rates) - min(selection_rates)
            max_selection_gap = gap if max_selection_gap is None else max(max_selection_gap, gap)
            tprs = [
                m.true_positive_rate for m in attribute_metrics if m.true_positive_rate is not None
            ]
            if len(tprs) >= 2:
                tpr_gap = max(tprs) - min(tprs)
                max_tpr_gap = tpr_gap if max_tpr_gap is None else max(max_tpr_gap, tpr_gap)

    return SubgroupAuditReport(
        threshold=threshold,
        metrics=metrics,
        max_selection_rate_gap=max_selection_gap,
        max_tpr_gap=max_tpr_gap,
        excluded_insufficient_groups=excluded,
    )
