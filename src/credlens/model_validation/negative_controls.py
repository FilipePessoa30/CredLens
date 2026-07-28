"""Replaces Phase 8's single fixed-band shuffled-target check
(`abs(auc - 0.5) <= 0.12`, evaluated on ONE shuffle) with a reproducible
permutation test (Phase 9 section 6): the target is independently
permuted `n_permutations` times, a fresh scaled logistic regression is
refit on train against each shuffled target, and evaluated against the
REAL validation labels - producing a full empirical null distribution
instead of a single point.

The old fixed band was too permissive for this sample size (18,000
training rows): a single unlucky shuffle could land anywhere in
[0.38, 0.62] and still "pass". A 100-permutation empirical p-value is
both stricter and self-calibrating - it does not need a hand-picked
tolerance at all.

Never touches the locked test set - every permutation is fit on TRAIN and
evaluated on VALIDATION, exactly like the diagnostic it replaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from credlens.model_validation.discrimination import independent_pr_auc, independent_roc_auc
from credlens.modeling.contracts import (
    load_evaluation_config,
    load_feature_registry,
    load_target_contract,
)
from credlens.modeling.features import engineer_features
from credlens.modeling.splitting import apply_split_assignment_table, load_split_assignment_table

EXPERIMENTS_DIR = Path("reports/modeling/experiments")


class PermutationTestError(Exception):
    """Raised when the permutation test cannot run (missing split/data)."""


@dataclass(frozen=True)
class PermutationTestReport:
    experiment_id: str
    n_permutations: int
    base_seed: int
    permutation_seeds: list[int]
    real_model_validation_roc_auc: float
    roc_auc_distribution: list[float]
    pr_auc_distribution: list[float]
    roc_auc_mean: float
    roc_auc_std: float
    roc_auc_min: float
    roc_auc_max: float
    roc_auc_percentiles: dict[str, float]
    mean_absolute_deviation_from_random: float
    empirical_p_value: float
    alpha: float
    max_permutation_mean_deviation_from_random_roc_auc: float
    passed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "n_permutations": self.n_permutations,
            "base_seed": self.base_seed,
            "permutation_seeds": self.permutation_seeds,
            "real_model_validation_roc_auc": round(self.real_model_validation_roc_auc, 6),
            "roc_auc_distribution": [round(v, 6) for v in self.roc_auc_distribution],
            "pr_auc_distribution": [round(v, 6) for v in self.pr_auc_distribution],
            "roc_auc_mean": round(self.roc_auc_mean, 6),
            "roc_auc_std": round(self.roc_auc_std, 6),
            "roc_auc_min": round(self.roc_auc_min, 6),
            "roc_auc_max": round(self.roc_auc_max, 6),
            "roc_auc_percentiles": {k: round(v, 6) for k, v in self.roc_auc_percentiles.items()},
            "mean_absolute_deviation_from_random": round(
                self.mean_absolute_deviation_from_random, 6
            ),
            "empirical_p_value": round(self.empirical_p_value, 6),
            "alpha": self.alpha,
            "max_permutation_mean_deviation_from_random_roc_auc": (
                self.max_permutation_mean_deviation_from_random_roc_auc
            ),
            "passed": self.passed,
            "reason": self.reason,
        }


def _fresh_scaled_logistic() -> Any:
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))


def run_permutation_negative_control(
    experiment_id: str,
    *,
    n_permutations: int,
    base_seed: int,
    alpha: float,
    max_permutation_mean_deviation: float,
    repo_root: Path | None = None,
) -> PermutationTestReport:
    repo_root = repo_root or Path.cwd()
    contract = load_target_contract(repo_root)
    registry = load_feature_registry(repo_root)
    config = load_evaluation_config(repo_root)

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

    _ = registry  # feature set is already the allowlisted engineered frame; no further check needed
    _ = config

    from credlens.modeling.registry import load_experiment

    experiment = load_experiment(repo_root / EXPERIMENTS_DIR / f"{experiment_id}.json")
    real_val_roc_auc = float(
        experiment.metrics["validation"]["logistic_regression"]["discrimination"]["roc_auc"]
    )

    permutation_seeds = [base_seed + i for i in range(n_permutations)]
    roc_aucs: list[float] = []
    pr_aucs: list[float] = []
    for seed in permutation_seeds:
        rng = np.random.default_rng(seed)
        shuffled = y_train.to_numpy(copy=True)
        rng.shuffle(shuffled)
        y_train_shuffled = pd.Series(shuffled, index=y_train.index, name=y_train.name)

        model = _fresh_scaled_logistic()
        model.fit(x_train, y_train_shuffled)
        p_val = pd.Series(model.predict_proba(x_val)[:, 1], index=x_val.index)

        roc_aucs.append(independent_roc_auc(y_val, p_val))
        pr_aucs.append(independent_pr_auc(y_val, p_val))

    roc_arr = np.array(roc_aucs)
    n_at_or_above_real = int(np.sum(roc_arr >= real_val_roc_auc))
    empirical_p_value = (n_at_or_above_real + 1) / (n_permutations + 1)
    mean_abs_deviation = float(np.mean(np.abs(roc_arr - 0.5)))
    roc_auc_mean = float(roc_arr.mean())

    p_value_ok = empirical_p_value <= alpha
    null_centered_ok = abs(roc_auc_mean - 0.5) <= max_permutation_mean_deviation
    passed = p_value_ok and null_centered_ok

    if passed:
        reason = (
            f"Real model validation ROC-AUC ({real_val_roc_auc:.4f}) exceeds "
            f"{n_permutations - n_at_or_above_real}/{n_permutations} permuted-target fits "
            f"(empirical p={empirical_p_value:.4f} <= alpha={alpha}); the permutation-null mean "
            f"ROC-AUC ({roc_auc_mean:.4f}) is within {max_permutation_mean_deviation} of random "
            "(0.5)."
        )
    elif not p_value_ok:
        reason = (
            f"Real model validation ROC-AUC ({real_val_roc_auc:.4f}) does not clearly exceed the "
            f"permutation null (empirical p={empirical_p_value:.4f} > alpha={alpha})."
        )
    else:
        reason = (
            f"The permutation-null mean ROC-AUC ({roc_auc_mean:.4f}) deviates from random (0.5) by "
            f"more than {max_permutation_mean_deviation} - the pipeline may retain a spurious "
            "association even under a permuted target."
        )

    return PermutationTestReport(
        experiment_id=experiment_id,
        n_permutations=n_permutations,
        base_seed=base_seed,
        permutation_seeds=permutation_seeds,
        real_model_validation_roc_auc=real_val_roc_auc,
        roc_auc_distribution=roc_aucs,
        pr_auc_distribution=pr_aucs,
        roc_auc_mean=roc_auc_mean,
        roc_auc_std=float(roc_arr.std(ddof=1)) if n_permutations > 1 else 0.0,
        roc_auc_min=float(roc_arr.min()),
        roc_auc_max=float(roc_arr.max()),
        roc_auc_percentiles={
            "p2_5": float(np.percentile(roc_arr, 2.5)),
            "p50": float(np.percentile(roc_arr, 50)),
            "p97_5": float(np.percentile(roc_arr, 97.5)),
        },
        mean_absolute_deviation_from_random=mean_abs_deviation,
        empirical_p_value=empirical_p_value,
        alpha=alpha,
        max_permutation_mean_deviation_from_random_roc_auc=max_permutation_mean_deviation,
        passed=passed,
        reason=reason,
    )
