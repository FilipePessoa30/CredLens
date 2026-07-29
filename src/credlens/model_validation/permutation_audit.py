"""Shared statistical diagnostics for the Phase 10 permutation controls
(gate A) - a closed-form theoretical null standard error for AUC under
pure label permutation, a self-calibrating centering test, an amplitude-
vs-theory check, and structural anomaly detection (duplicated
permutations, single-class permutations, index misalignment).

None of these use a fixed, arbitrary tolerance (Phase 10 section 5.3):
centering is a z-test against the null distribution's OWN standard error
of the mean, which shrinks automatically as more permutations are run;
amplitude is the ratio of the OBSERVED standard deviation to the
THEORETICAL one implied by the actual validation sample's class counts
(Hanley & McNeil / Mann-Whitney U variance under the null of no
association) - never a hand-picked absolute number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


def theoretical_null_auc_se(n_pos: int, n_neg: int) -> float:
    """Closed-form standard error of the ROC-AUC (Mann-Whitney U
    statistic, rescaled) under the null hypothesis of NO association
    between scores and labels - the large-sample approximation
    Var(AUC) = (n_pos + n_neg) / (12 * n_pos * n_neg), i.e. treating the
    U-statistic as approximately normal (valid for the sample sizes this
    project's validation/test partitions always have, n >= 500)."""
    if n_pos <= 0 or n_neg <= 0:
        raise ValueError("theoretical_null_auc_se requires at least one case of each class.")
    n = n_pos + n_neg
    return math.sqrt(n / (12.0 * n_pos * n_neg))


@dataclass(frozen=True)
class CenteringTestResult:
    observed_mean: float
    expected_mean: float
    standard_error_of_mean: float
    z_statistic: float
    sigma_multiplier: float
    centered: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_mean": round(self.observed_mean, 6),
            "expected_mean": self.expected_mean,
            "standard_error_of_mean": round(self.standard_error_of_mean, 6),
            "z_statistic": round(self.z_statistic, 4),
            "sigma_multiplier": self.sigma_multiplier,
            "centered": self.centered,
        }


def centering_test(
    distribution: np.ndarray, *, expected_mean: float = 0.5, sigma_multiplier: float = 3.0
) -> CenteringTestResult:
    """Two-sided z-test of `distribution`'s own mean against
    `expected_mean`, using `distribution`'s own sample standard error of
    the mean (std / sqrt(n)) - a threshold that tightens automatically
    with more permutations, never a fixed absolute band."""
    n = len(distribution)
    observed_mean = float(np.mean(distribution))
    sample_std = float(np.std(distribution, ddof=1)) if n > 1 else 0.0
    se_of_mean = sample_std / math.sqrt(n) if n > 0 else float("inf")
    z_statistic = (observed_mean - expected_mean) / se_of_mean if se_of_mean > 0 else 0.0
    centered = abs(z_statistic) <= sigma_multiplier
    return CenteringTestResult(
        observed_mean=observed_mean,
        expected_mean=expected_mean,
        standard_error_of_mean=se_of_mean,
        z_statistic=z_statistic,
        sigma_multiplier=sigma_multiplier,
        centered=centered,
    )


@dataclass(frozen=True)
class AmplitudeTestResult:
    observed_std: float
    theoretical_se: float
    ratio: float
    ratio_min: float
    ratio_max: float
    within_expected_amplitude: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_std": round(self.observed_std, 6),
            "theoretical_se": round(self.theoretical_se, 6),
            "ratio": round(self.ratio, 4),
            "ratio_min": self.ratio_min,
            "ratio_max": self.ratio_max,
            "within_expected_amplitude": self.within_expected_amplitude,
        }


def amplitude_test(
    distribution: np.ndarray,
    theoretical_se: float,
    *,
    ratio_min: float = 1.0 / 3.0,
    ratio_max: float = 3.0,
) -> AmplitudeTestResult:
    """Only meaningful for a permutation control with a closed-form
    theoretical null SE (Control 1). Compares the OBSERVED standard
    deviation of the null distribution against that theoretical value -
    a ratio far from 1 (outside [ratio_min, ratio_max]) signals either an
    implementation bug or a genuinely different data-generating process,
    not a hand-picked absolute spread."""
    observed_std = float(np.std(distribution, ddof=1)) if len(distribution) > 1 else 0.0
    ratio = observed_std / theoretical_se if theoretical_se > 0 else float("inf")
    within = ratio_min <= ratio <= ratio_max
    return AmplitudeTestResult(
        observed_std=observed_std,
        theoretical_se=theoretical_se,
        ratio=ratio,
        ratio_min=ratio_min,
        ratio_max=ratio_max,
        within_expected_amplitude=within,
    )


@dataclass(frozen=True)
class PermutationRow:
    permutation_id: int
    seed: int
    train_size: int
    validation_size: int
    n_positive_train: int
    n_negative_train: int
    n_positive_val: int
    n_negative_val: int
    roc_auc: float | None
    pr_auc: float | None
    status: str
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "permutation_id": self.permutation_id,
            "seed": self.seed,
            "train_size": self.train_size,
            "validation_size": self.validation_size,
            "n_positive_train": self.n_positive_train,
            "n_negative_train": self.n_negative_train,
            "n_positive_val": self.n_positive_val,
            "n_negative_val": self.n_negative_val,
            "roc_auc": round(self.roc_auc, 6) if self.roc_auc is not None else None,
            "pr_auc": round(self.pr_auc, 6) if self.pr_auc is not None else None,
            "status": self.status,
            "warnings": self.warnings,
        }


def detect_duplicate_permutations(fingerprints: list[str]) -> list[int]:
    """Returns the (0-indexed) positions of any fingerprint that repeats
    an EARLIER one - evidence that two "different" permutations actually
    produced the identical shuffle (a seeding bug), rather than being
    independently random. `fingerprints` is expected to be a per-
    permutation hash of the shuffled label array (or score array)."""
    seen: dict[str, int] = {}
    duplicates = []
    for i, fingerprint in enumerate(fingerprints):
        if fingerprint in seen:
            duplicates.append(i)
        else:
            seen[fingerprint] = i
    return duplicates
