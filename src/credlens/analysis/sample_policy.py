"""Minimum-sample policy for segmented analytical breakdowns (Phase 7
gate B). Replaces Phase 6's flat `MIN_SEGMENT_OBSERVATIONS = 10` cutoff -
too low to sustain executive-facing reading, per this phase's own
findings - with a three-tier, versioned, configurable classification:

  - n < insufficient_below: "insufficient" - never ranked, never
    recommended, never called out as best/worst; the count itself stays
    visible for audit.
  - insufficient_below <= n < limited_below: "limited" - the metric is
    shown, but with a visible caution label and no conclusive language.
  - n >= limited_below: "adequate" - a descriptive-adequacy convention,
    never a formal statistical power guarantee.

Every segmented query/report/dashboard component in this project must
classify through this module - never re-declare its own threshold. See
`analysis/specifications/segmentation_policy.md` for the full rationale
and `analysis/specifications/segmentation_policy.yaml` for the versioned
policy this loads.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

SampleClassification = Literal["insufficient", "limited", "adequate"]

DEFAULT_POLICY_PATH = Path("analysis/specifications/segmentation_policy.yaml")

# Human-readable labels - never phrased as a statistical guarantee (Phase
# 7 gate B: "Esses rótulos não devem ser descritos como garantia
# estatística").
CLASSIFICATION_LABELS: dict[SampleClassification, str] = {
    "insufficient": "Insufficient sample - not ranked, not recommended, count shown for audit only",
    "limited": "Limited sample - descriptive only, avoid conclusive language",
    "adequate": "Adequate descriptive sample - not a statistical power guarantee",
}

_SEVERITY: dict[SampleClassification, int] = {"adequate": 0, "limited": 1, "insufficient": 2}


class SamplePolicyError(Exception):
    """Raised when the segmentation sample-size policy is missing or invalid."""


@dataclass(frozen=True)
class SamplePolicy:
    insufficient_below: int
    limited_below: int

    def __post_init__(self) -> None:
        if self.insufficient_below <= 0 or self.limited_below <= 0:
            raise SamplePolicyError("Sample policy thresholds must be positive integers.")
        if self.insufficient_below >= self.limited_below:
            raise SamplePolicyError(
                "'insufficient_below' must be strictly less than 'limited_below' "
                f"(got {self.insufficient_below} >= {self.limited_below})."
            )

    def classify(self, n: int) -> SampleClassification:
        if n < self.insufficient_below:
            return "insufficient"
        if n < self.limited_below:
            return "limited"
        return "adequate"

    def to_dict(self) -> dict[str, int]:
        return {"insufficient_below": self.insufficient_below, "limited_below": self.limited_below}


# The documented default (Phase 7 gate B) - used only if the versioned
# policy file is somehow absent; the file itself is the source of truth.
DEFAULT_POLICY = SamplePolicy(insufficient_below=30, limited_below=100)


def load_sample_policy(path: Path | None = None) -> SamplePolicy:
    """Loads the versioned segmentation sample-size policy from YAML.
    Falls back to `DEFAULT_POLICY` (30 / 100) if the file is absent -
    never silently to 0/None, and never to Phase 6's old 10."""
    policy_path = path or DEFAULT_POLICY_PATH
    if not policy_path.is_file():
        return DEFAULT_POLICY
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or not isinstance(raw.get("segmentation"), dict):
        raise SamplePolicyError(f"'{policy_path}' must contain a top-level 'segmentation' mapping.")
    section = raw["segmentation"]
    try:
        insufficient_below = int(section["insufficient_below"])
        limited_below = int(section["limited_below"])
    except KeyError as exc:
        raise SamplePolicyError(f"'{policy_path}' is missing key {exc}.") from exc
    return SamplePolicy(insufficient_below=insufficient_below, limited_below=limited_below)


def classify_sample_size(n: int, policy: SamplePolicy | None = None) -> SampleClassification:
    """Classifies a single segment's observation count. `policy` is
    injectable for tests; production callers should normally omit it and
    let the versioned file be read once per caller."""
    return (policy or load_sample_policy()).classify(n)


def combine_classifications(
    *counts: int, policy: SamplePolicy | None = None
) -> SampleClassification:
    """Combines several related counts (e.g. shared/baseline-only/
    scenario-only booked contracts) into one overall classification -
    the LEAST favorable of the group, so a comparison is never presented
    as adequate when any side of it is not."""
    if not counts:
        raise ValueError("combine_classifications requires at least one count.")
    p = policy or load_sample_policy()
    return max((p.classify(n) for n in counts), key=lambda c: _SEVERITY[c])


def is_reportable(classification: SampleClassification) -> bool:
    """Whether a segment may be ranked, recommended, or cited as a
    best/worst finding (Phase 7 gate B section 5.1). `limited` may still
    be shown as a plain descriptive figure - only `insufficient` is
    excluded from ranking/recommendation."""
    return classification != "insufficient"
