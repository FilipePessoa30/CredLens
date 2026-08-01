"""Two complementary permutation controls (Phase 10 gate A) - Phase 9's
single pipeline-retrain-only control (`abs(auc - 0.5) <= 0.12` in Phase 8,
then `abs(mean - 0.5) <= 0.05` in Phase 9) is replaced by TWO controls
reported side by side, plus a full per-permutation audit table for each.

**Why two controls.** Auditing Phase 9's reported null distribution
(mean=0.4907, std=0.0631, range=[0.329, 0.675] over 100 permutations)
found no alignment/indexing/seeding bug - every index, class count, and
seed checked out. The width is the textbook consequence of the control's
OWN design: it retrains the full pipeline on a shuffled TRAINING target
each time, so its null variance includes model-refitting noise on top of
label-shuffling noise, and has no simple closed form. A second control -
permuting only the VALIDATION labels against the already-frozen,
never-retrained validation scores - isolates the label-shuffling
component alone, which DOES have a closed-form expected standard error
(`credlens.model_validation.permutation_audit.theoretical_null_auc_se`).
Empirically, Control 1's observed std (0.00883 over 999 permutations)
matches that theoretical value (0.00898) almost exactly (ratio 0.98) -
confirming both the absence of a bug and Control 2's width is expected,
not evidence of a problem.

Neither control ever touches the locked test set.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from credlens.model_validation.discrimination import independent_pr_auc, independent_roc_auc
from credlens.model_validation.permutation_audit import (
    AmplitudeTestResult,
    CenteringTestResult,
    PermutationRow,
    amplitude_test,
    centering_test,
    detect_duplicate_permutations,
    theoretical_null_auc_se,
)
from credlens.modeling.contracts import load_target_contract
from credlens.modeling.features import engineer_features
from credlens.modeling.splitting import apply_split_assignment_table, load_split_assignment_table

EXPERIMENTS_DIR = Path("reports/modeling/experiments")
TABLES_DIR = Path("reports/modeling/tables")


class PermutationTestError(Exception):
    """Raised when a permutation control cannot run (missing split/data)."""


def _fresh_scaled_logistic() -> Any:
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))


def _fingerprint(values: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()


# --- Control 1: score-label permutation (frozen scores, no retraining) -----


@dataclass(frozen=True)
class ScoreLabelPermutationReport:
    experiment_id: str
    n_permutations: int
    base_seed: int
    real_roc_auc: float
    roc_auc_distribution: list[float]
    pr_auc_distribution: list[float]
    audit_table: list[PermutationRow]
    centering: CenteringTestResult
    amplitude: AmplitudeTestResult
    empirical_p_value: float
    alpha: float
    duplicate_permutation_indices: list[int]
    n_single_class_permutations: int
    passed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "control": "control1_score_label",
            "n_permutations": self.n_permutations,
            "base_seed": self.base_seed,
            "real_roc_auc": round(self.real_roc_auc, 6),
            "roc_auc_distribution": [round(v, 6) for v in self.roc_auc_distribution],
            "pr_auc_distribution": [round(v, 6) for v in self.pr_auc_distribution],
            "centering": self.centering.to_dict(),
            "amplitude": self.amplitude.to_dict(),
            "empirical_p_value": round(self.empirical_p_value, 6),
            "alpha": self.alpha,
            "duplicate_permutation_indices": self.duplicate_permutation_indices,
            "n_single_class_permutations": self.n_single_class_permutations,
            "passed": self.passed,
            "reason": self.reason,
        }


def run_score_label_permutation_control(
    experiment_id: str,
    *,
    n_permutations: int,
    base_seed: int,
    alpha: float,
    centering_sigma_multiplier: float,
    amplitude_ratio_min: float,
    amplitude_ratio_max: float,
    repo_root: Path | None = None,
) -> ScoreLabelPermutationReport:
    """Permutes ONLY the validation labels against the already-frozen
    validation predictions (`<experiment_id>__predictions_val.csv`,
    written once by `credlens.modeling.reporting.evaluate_experiment`,
    never recomputed here) - no retraining, no re-scoring. The classical
    exact-reference-distribution permutation test for "do these frozen
    scores have a real association with the label"."""
    repo_root = repo_root or Path.cwd()
    predictions_path = repo_root / TABLES_DIR / f"{experiment_id}__predictions_val.csv"
    if not predictions_path.is_file():
        raise PermutationTestError(
            f"No frozen validation predictions at '{predictions_path}' - run "
            "'credlens model evaluate' first."
        )
    predictions = pd.read_csv(predictions_path)
    y_val = predictions["y_true"].to_numpy()
    p_val = predictions["logistic_regression"].to_numpy()
    n_pos = int(y_val.sum())
    n_neg = len(y_val) - n_pos
    if n_pos == 0 or n_neg == 0:
        raise PermutationTestError("Frozen validation set has only one class - cannot compute AUC.")

    real_roc_auc = independent_roc_auc(pd.Series(y_val), pd.Series(p_val))

    seeds = [base_seed + i for i in range(n_permutations)]
    rows: list[PermutationRow] = []
    fingerprints: list[str] = []
    roc_aucs: list[float] = []
    pr_aucs: list[float] = []
    n_single_class = 0
    for i, seed in enumerate(seeds):
        rng = np.random.default_rng(seed)
        shuffled_y = y_val.copy()
        rng.shuffle(shuffled_y)
        fingerprints.append(_fingerprint(shuffled_y))

        row_warnings: list[str] = []
        status = "ok"
        n_pos_shuf = int(shuffled_y.sum())
        n_neg_shuf = len(shuffled_y) - n_pos_shuf
        roc_auc_i: float | None
        pr_auc_i: float | None
        if n_pos_shuf == 0 or n_neg_shuf == 0:
            status = "single_class"
            row_warnings.append("Shuffled validation labels contain only one class.")
            roc_auc_i, pr_auc_i = None, None
            n_single_class += 1
        else:
            roc_auc_i = independent_roc_auc(pd.Series(shuffled_y), pd.Series(p_val))
            pr_auc_i = independent_pr_auc(pd.Series(shuffled_y), pd.Series(p_val))
            roc_aucs.append(roc_auc_i)
            pr_aucs.append(pr_auc_i)

        rows.append(
            PermutationRow(
                permutation_id=i,
                seed=seed,
                train_size=0,
                validation_size=len(shuffled_y),
                n_positive_train=0,
                n_negative_train=0,
                n_positive_val=n_pos_shuf,
                n_negative_val=n_neg_shuf,
                roc_auc=roc_auc_i,
                pr_auc=pr_auc_i,
                status=status,
                warnings=row_warnings,
            )
        )

    duplicate_indices = detect_duplicate_permutations(fingerprints)
    roc_arr = np.array(roc_aucs)
    centering = centering_test(
        roc_arr, expected_mean=0.5, sigma_multiplier=centering_sigma_multiplier
    )
    theoretical_se = theoretical_null_auc_se(n_pos, n_neg)
    amplitude = amplitude_test(
        roc_arr, theoretical_se, ratio_min=amplitude_ratio_min, ratio_max=amplitude_ratio_max
    )

    n_at_or_above = int(np.sum(roc_arr >= real_roc_auc))
    empirical_p_value = (n_at_or_above + 1) / (len(roc_arr) + 1)

    structural_ok = not duplicate_indices and n_single_class == 0
    p_value_ok = empirical_p_value <= alpha
    passed = (
        structural_ok and p_value_ok and centering.centered and amplitude.within_expected_amplitude
    )

    if not structural_ok:
        reason = (
            f"Structural anomaly: {len(duplicate_indices)} duplicate permutation(s), "
            f"{n_single_class} single-class permutation(s)."
        )
    elif not p_value_ok:
        reason = (
            f"Real ROC-AUC ({real_roc_auc:.4f}) does not clearly exceed the label-permutation "
            f"null (empirical p={empirical_p_value:.4f} > alpha={alpha})."
        )
    elif not centering.centered:
        reason = (
            f"Null distribution not centered on 0.5 (z={centering.z_statistic:.2f}, "
            f"threshold={centering_sigma_multiplier} sigma)."
        )
    elif not amplitude.within_expected_amplitude:
        reason = (
            f"Null standard deviation ({amplitude.observed_std:.5f}) deviates from the "
            f"theoretical value ({amplitude.theoretical_se:.5f}) by more than expected "
            f"(ratio={amplitude.ratio:.2f}, expected in "
            f"[{amplitude_ratio_min:.2f}, {amplitude_ratio_max:.2f}])."
        )
    else:
        reason = (
            f"Real ROC-AUC ({real_roc_auc:.4f}) exceeds {len(roc_arr) - n_at_or_above}/"
            f"{len(roc_arr)} label permutations (empirical p={empirical_p_value:.4f}); null mean "
            f"{centering.observed_mean:.4f} (z={centering.z_statistic:.2f}) and std "
            f"{amplitude.observed_std:.5f} (ratio to theory={amplitude.ratio:.2f}) both within "
            "expectation."
        )

    return ScoreLabelPermutationReport(
        experiment_id=experiment_id,
        n_permutations=n_permutations,
        base_seed=base_seed,
        real_roc_auc=real_roc_auc,
        roc_auc_distribution=roc_aucs,
        pr_auc_distribution=pr_aucs,
        audit_table=rows,
        centering=centering,
        amplitude=amplitude,
        empirical_p_value=empirical_p_value,
        alpha=alpha,
        duplicate_permutation_indices=duplicate_indices,
        n_single_class_permutations=n_single_class,
        passed=passed,
        reason=reason,
    )


# --- Control 2: full pipeline retrain (Phase 9's original control) ---------


@dataclass(frozen=True)
class PipelineRetrainPermutationReport:
    experiment_id: str
    n_permutations: int
    base_seed: int
    real_model_validation_roc_auc: float
    roc_auc_distribution: list[float]
    pr_auc_distribution: list[float]
    audit_table: list[PermutationRow]
    centering: CenteringTestResult
    observed_std: float
    control1_theoretical_se_for_reference: float
    empirical_p_value: float
    alpha: float
    duplicate_permutation_indices: list[int]
    n_single_class_permutations: int
    passed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "control": "control2_pipeline_retrain",
            "n_permutations": self.n_permutations,
            "base_seed": self.base_seed,
            "real_model_validation_roc_auc": round(self.real_model_validation_roc_auc, 6),
            "roc_auc_distribution": [round(v, 6) for v in self.roc_auc_distribution],
            "pr_auc_distribution": [round(v, 6) for v in self.pr_auc_distribution],
            "centering": self.centering.to_dict(),
            "observed_std": round(self.observed_std, 6),
            "control1_theoretical_se_for_reference": round(
                self.control1_theoretical_se_for_reference, 6
            ),
            "std_ratio_to_control1_theory_informational_only": (
                round(self.observed_std / self.control1_theoretical_se_for_reference, 4)
                if self.control1_theoretical_se_for_reference > 0
                else None
            ),
            "empirical_p_value": round(self.empirical_p_value, 6),
            "alpha": self.alpha,
            "duplicate_permutation_indices": self.duplicate_permutation_indices,
            "n_single_class_permutations": self.n_single_class_permutations,
            "passed": self.passed,
            "reason": self.reason,
        }


def run_pipeline_retrain_permutation_control(
    experiment_id: str,
    *,
    n_permutations: int,
    base_seed: int,
    alpha: float,
    centering_sigma_multiplier: float,
    repo_root: Path | None = None,
) -> PipelineRetrainPermutationReport:
    """Permutes the TRAINING target, refits the full pipeline from
    scratch, and scores on the untouched validation set - Phase 9's
    original control, preserved, now with a full per-permutation audit
    table and NO fixed amplitude tolerance (no closed-form null exists
    for a retraining-based test; Control 1 above covers that check)."""
    repo_root = repo_root or Path.cwd()
    contract = load_target_contract(repo_root)

    from credlens.modeling.data import load_uci_default_credit

    df = load_uci_default_credit(repo_root)
    split_path = repo_root / EXPERIMENTS_DIR / experiment_id / "split_assignment.csv"
    if not split_path.is_file():
        raise PermutationTestError(
            f"No split assignment table for '{experiment_id}' at '{split_path}'."
        )
    table = load_split_assignment_table(split_path)
    assignment = apply_split_assignment_table(df, table, id_column=contract.identifier_column)

    features = engineer_features(df)
    target = df[contract.target_column]
    x_train = features.loc[assignment.train_index]
    y_train = target.loc[assignment.train_index]
    x_val = features.loc[assignment.validation_index]
    y_val = target.loc[assignment.validation_index]

    from credlens.modeling.registry import load_experiment

    experiment = load_experiment(repo_root / EXPERIMENTS_DIR / f"{experiment_id}.json")
    real_val_roc_auc = float(
        experiment.metrics["validation"]["logistic_regression"]["discrimination"]["roc_auc"]
    )
    n_pos_val_real = int(y_val.sum())
    n_neg_val_real = len(y_val) - n_pos_val_real

    seeds = [base_seed + i for i in range(n_permutations)]
    rows: list[PermutationRow] = []
    fingerprints: list[str] = []
    roc_aucs: list[float] = []
    pr_aucs: list[float] = []
    n_single_class = 0
    y_train_index_before = list(y_train.index)
    x_train_index_before = list(x_train.index)
    for i, seed in enumerate(seeds):
        rng = np.random.default_rng(seed)
        shuffled = y_train.to_numpy(copy=True)
        rng.shuffle(shuffled)
        fingerprints.append(_fingerprint(shuffled))
        y_train_shuffled = pd.Series(shuffled, index=y_train.index, name=y_train.name)

        # Alignment guard - train features/labels must remain positionally
        # identical to before the shuffle; only VALUES may have moved.
        index_shifted = (
            list(y_train_shuffled.index) != y_train_index_before
            or list(x_train.index) != x_train_index_before
        )
        if index_shifted:
            raise PermutationTestError(
                f"Index misalignment detected at permutation {i} (seed={seed})."
            )

        n_pos_train = int(y_train_shuffled.sum())
        n_neg_train = len(y_train_shuffled) - n_pos_train
        row_warnings: list[str] = []
        status = "ok"
        roc_auc_i: float | None
        pr_auc_i: float | None
        if n_pos_train == 0 or n_neg_train == 0:
            status = "single_class"
            row_warnings.append("Shuffled training target contains only one class.")
            roc_auc_i, pr_auc_i = None, None
            n_single_class += 1
        else:
            model = _fresh_scaled_logistic()
            model.fit(x_train, y_train_shuffled)
            p_val = pd.Series(model.predict_proba(x_val)[:, 1], index=x_val.index)
            roc_auc_i = independent_roc_auc(y_val, p_val)
            pr_auc_i = independent_pr_auc(y_val, p_val)
            roc_aucs.append(roc_auc_i)
            pr_aucs.append(pr_auc_i)

        rows.append(
            PermutationRow(
                permutation_id=i,
                seed=seed,
                train_size=len(y_train_shuffled),
                validation_size=len(y_val),
                n_positive_train=n_pos_train,
                n_negative_train=n_neg_train,
                n_positive_val=n_pos_val_real,
                n_negative_val=n_neg_val_real,
                roc_auc=roc_auc_i,
                pr_auc=pr_auc_i,
                status=status,
                warnings=row_warnings,
            )
        )

    duplicate_indices = detect_duplicate_permutations(fingerprints)
    roc_arr = np.array(roc_aucs)
    centering = centering_test(
        roc_arr, expected_mean=0.5, sigma_multiplier=centering_sigma_multiplier
    )
    control1_theoretical_se = theoretical_null_auc_se(n_pos_val_real, n_neg_val_real)

    n_at_or_above = int(np.sum(roc_arr >= real_val_roc_auc))
    empirical_p_value = (n_at_or_above + 1) / (len(roc_arr) + 1)

    structural_ok = not duplicate_indices and n_single_class == 0
    p_value_ok = empirical_p_value <= alpha
    passed = structural_ok and p_value_ok and centering.centered

    if not structural_ok:
        reason = (
            f"Structural anomaly: {len(duplicate_indices)} duplicate permutation(s), "
            f"{n_single_class} single-class training permutation(s)."
        )
    elif not p_value_ok:
        reason = (
            f"Real model validation ROC-AUC ({real_val_roc_auc:.4f}) does not clearly exceed "
            f"the permutation null (empirical p={empirical_p_value:.4f} > alpha={alpha})."
        )
    elif not centering.centered:
        reason = (
            f"Null distribution not centered on 0.5 (z={centering.z_statistic:.2f}, "
            f"threshold={centering_sigma_multiplier} sigma)."
        )
    else:
        reason = (
            f"Real model validation ROC-AUC ({real_val_roc_auc:.4f}) exceeds "
            f"{len(roc_arr) - n_at_or_above}/{len(roc_arr)} permuted-target refits (empirical "
            f"p={empirical_p_value:.4f}); null mean {centering.observed_mean:.4f} "
            f"(z={centering.z_statistic:.2f}) is centered. Observed std "
            f"{float(roc_arr.std(ddof=1)) if len(roc_arr) > 1 else 0.0:.5f} "
            f"is wider than Control 1's theoretical label-permutation-only SE "
            f"({control1_theoretical_se:.5f}) - expected, since this control's "
            "variance includes model-refitting noise (see module docstring)."
        )

    return PipelineRetrainPermutationReport(
        experiment_id=experiment_id,
        n_permutations=n_permutations,
        base_seed=base_seed,
        real_model_validation_roc_auc=real_val_roc_auc,
        roc_auc_distribution=roc_aucs,
        pr_auc_distribution=pr_aucs,
        audit_table=rows,
        centering=centering,
        observed_std=float(roc_arr.std(ddof=1)) if len(roc_arr) > 1 else 0.0,
        control1_theoretical_se_for_reference=control1_theoretical_se,
        empirical_p_value=empirical_p_value,
        alpha=alpha,
        duplicate_permutation_indices=duplicate_indices,
        n_single_class_permutations=n_single_class,
        passed=passed,
        reason=reason,
    )
