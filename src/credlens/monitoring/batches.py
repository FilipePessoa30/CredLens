"""Builds the 12 simulated monitoring batches (Phase 9 section 14) by
partitioning the OFFICIALLY LOCKED test set into 12 equal, non-overlapping,
ID-ordered slices (`source_partition` 1..12 - an arbitrary acquisition-
order slice, never a real calendar date) and perturbing each according to
its own `simulation_scenario`. Every batch is built here in RAW (pre-
feature-engineering) form - `credlens.monitoring.runner` is responsible
for running each batch through the input-contract gate first (which may
reject/quarantine rows) before engineering features and scoring, exactly
the order a real batch-scoring pipeline would use.

Reusing the test set here is safe: the registered model is already
frozen (Phase 8), nothing here retunes/recalibrates/reselects a
threshold, and this is read-only scoring for a monitoring demonstration -
kept entirely separate from the one official test-set evaluation already
frozen in `reports/model_validation/evidence/`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from credlens.modeling.contracts import load_target_contract
from credlens.modeling.registry import load_model_candidate_manifest
from credlens.modeling.splitting import apply_split_assignment_table, load_split_assignment_table

BATCHES_DIR = Path("reports/monitoring/runs")
MODELS_DIR = Path("reports/modeling/models")
EXPERIMENTS_DIR = Path("reports/modeling/experiments")

_DELINQUENCY_COLUMNS = ["X6", "X7", "X8", "X9", "X10", "X11"]
_BILL_COLUMNS = ["X12", "X13", "X14", "X15", "X16", "X17"]
_PAYMENT_COLUMNS = ["X18", "X19", "X20", "X21", "X22", "X23"]


class BatchBuildError(Exception):
    """Raised when the batch set cannot be built (missing model/split)."""


def _perturb(raw: pd.DataFrame, spec: dict[str, Any], rng: np.random.Generator) -> pd.DataFrame:
    scenario = spec["simulation_scenario"]
    out = raw.copy()

    if scenario == "baseline_like" or scenario == "label_delay":
        return out
    if scenario == "missingness_drift":
        mask = rng.random(len(out)) < float(spec["missingness_extra_fraction"])
        out.loc[mask, _DELINQUENCY_COLUMNS[0]] = np.nan
        return out
    if scenario == "utilization_shift":
        out[_BILL_COLUMNS] = out[_BILL_COLUMNS] * float(spec["utilization_shift_multiplier"])
        return out
    if scenario == "payment_reduction":
        out[_PAYMENT_COLUMNS] = out[_PAYMENT_COLUMNS] * float(spec["payment_shrink_factor"])
        return out
    if scenario == "delinquency_worsening":
        steps = int(spec["delinquency_worsening_steps"])
        out[_DELINQUENCY_COLUMNS] = (out[_DELINQUENCY_COLUMNS] + steps).clip(lower=-2, upper=9)
        return out
    if scenario == "out_of_domain_codes":
        code = int(spec["out_of_domain_delinquency_code"])
        fraction = float(spec["affected_fraction"])
        mask = rng.random((len(out), len(_DELINQUENCY_COLUMNS))) < fraction
        values = out[_DELINQUENCY_COLUMNS].to_numpy(dtype=float)
        values[mask] = code
        out[_DELINQUENCY_COLUMNS] = values
        return out
    if scenario == "feature_range_violation":
        fraction = float(spec["affected_fraction"])
        mask = rng.random(len(out)) < fraction
        out.loc[mask, "X12"] = (
            out.loc[mask, "X12"].abs() * float(spec["impossible_bill_multiplier"]) + 1.0
        )
        return out
    if scenario == "prevalence_drift":
        return _prevalence_drift(out, float(spec["target_prevalence"]), rng)
    if scenario == "score_distribution_shift":
        out[_BILL_COLUMNS] = out[_BILL_COLUMNS] * float(spec["utilization_shift_multiplier"])
        steps = int(spec["delinquency_worsening_steps"])
        out[_DELINQUENCY_COLUMNS] = (out[_DELINQUENCY_COLUMNS] + steps).clip(lower=-2, upper=9)
        return out
    if scenario == "subgroup_composition_shift":
        return _subgroup_composition_shift(
            out, spec["oversampled_age_bucket"], float(spec["oversample_fraction"]), rng
        )
    if scenario == "corrupted_schema":
        return out.drop(columns=[spec["drop_column"]])
    raise ValueError(f"Unknown monitoring scenario '{scenario}'.")


def _prevalence_drift(
    raw: pd.DataFrame, target_prevalence: float, rng: np.random.Generator
) -> pd.DataFrame:
    y = raw["Y"]
    positive_idx = raw.index[y == 1]
    negative_idx = raw.index[y == 0]
    n_pos, n_neg = len(positive_idx), len(negative_idx)
    if n_pos == 0 or n_neg == 0:
        return raw
    if target_prevalence < n_pos / (n_pos + n_neg):
        target_n_pos = round(target_prevalence * n_neg / (1 - target_prevalence))
        keep_pos = pd.Index(rng.choice(positive_idx, size=min(target_n_pos, n_pos), replace=False))
        keep_neg = negative_idx
    else:
        target_n_neg = round(n_pos * (1 - target_prevalence) / target_prevalence)
        keep_neg = pd.Index(rng.choice(negative_idx, size=min(target_n_neg, n_neg), replace=False))
        keep_pos = positive_idx
    keep_index = keep_pos.union(keep_neg)
    return raw.loc[keep_index]


def _subgroup_composition_shift(
    raw: pd.DataFrame, age_bucket: list[int], oversample_fraction: float, rng: np.random.Generator
) -> pd.DataFrame:
    low, high = age_bucket
    matching = raw[(raw["X5"] >= low) & (raw["X5"] < high)]
    other = raw[~((raw["X5"] >= low) & (raw["X5"] < high))]
    n_total = len(raw)
    n_matching_target = round(oversample_fraction * n_total)
    n_other_target = n_total - n_matching_target

    matching_sample = (
        matching.sample(n=n_matching_target, replace=True, random_state=int(rng.integers(0, 2**31)))
        if len(matching) > 0 and n_matching_target > 0
        else matching.iloc[0:0]
    )
    other_sample = (
        other.sample(n=n_other_target, replace=True, random_state=int(rng.integers(0, 2**31)))
        if len(other) > 0 and n_other_target > 0
        else other.iloc[0:0]
    )
    return pd.concat([matching_sample, other_sample], ignore_index=False)


def _sorted_locked_test_set(model_id: str, *, repo_root: Path) -> pd.DataFrame:
    manifest = load_model_candidate_manifest(model_id, repo_root / MODELS_DIR)
    experiment_id = manifest.experiment_id
    contract = load_target_contract(repo_root)

    from credlens.modeling.data import load_uci_default_credit

    df = load_uci_default_credit(repo_root)
    split_table = load_split_assignment_table(
        repo_root / EXPERIMENTS_DIR / experiment_id / "split_assignment.csv"
    )
    assignment = apply_split_assignment_table(df, split_table, id_column=contract.identifier_column)
    return (
        df.loc[assignment.test_index].sort_values(contract.identifier_column).reset_index(drop=True)
    )


def load_unperturbed_partition(
    model_id: str, source_partition: int, batch_size: int, *, repo_root: Path | None = None
) -> pd.DataFrame:
    """The exact pre-perturbation raw slice for `source_partition` - used
    ONLY to compute rank-stability twins in `credlens.monitoring.runner`,
    never written to disk as a batch itself."""
    repo_root = repo_root or Path.cwd()
    test_df = _sorted_locked_test_set(model_id, repo_root=repo_root)
    start = (source_partition - 1) * batch_size
    return test_df.iloc[start : start + batch_size].copy()


def build_batches(
    model_id: str, scenarios_config: Any, *, repo_root: Path | None = None
) -> list[tuple[dict[str, Any], pd.DataFrame]]:
    repo_root = repo_root or Path.cwd()
    test_df = _sorted_locked_test_set(model_id, repo_root=repo_root)

    batch_size = scenarios_config.batch_size
    batches = scenarios_config.batches
    if batch_size * len(batches) > len(test_df):
        raise BatchBuildError(
            f"batch_size ({batch_size}) x n_batches ({len(batches)}) exceeds the locked test set "
            f"size ({len(test_df)}) - batches would overlap."
        )

    rng = np.random.default_rng(scenarios_config.seed)
    results = []
    for spec in batches:
        partition = int(spec["source_partition"])
        start = (partition - 1) * batch_size
        raw_slice = test_df.iloc[start : start + batch_size].copy()
        perturbed = _perturb(raw_slice, spec, rng)
        results.append((spec, perturbed))
    return results


def write_batches(
    batch_set_id: str,
    batches: list[tuple[dict[str, Any], pd.DataFrame]],
    *,
    repo_root: Path | None = None,
) -> Path:
    repo_root = repo_root or Path.cwd()
    out_dir = repo_root / BATCHES_DIR / batch_set_id / "batches"
    if out_dir.is_dir() and any(out_dir.iterdir()):
        raise BatchBuildError(f"Batch set '{batch_set_id}' already exists at '{out_dir}'.")
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_entries = []
    for spec, batch_df in batches:
        path = out_dir / f"batch_{spec['batch_sequence']:02d}.csv"
        batch_df.to_csv(path, index=False)
        manifest_entries.append(
            {**spec, "n_rows": len(batch_df), "path": str(path.relative_to(repo_root))}
        )

    manifest_path = out_dir.parent / "batch_manifest.json"
    manifest_path.write_text(
        json.dumps({"batch_set_id": batch_set_id, "batches": manifest_entries}, indent=2),
        encoding="utf-8",
    )
    return manifest_path


def load_batch_manifest(batch_set_id: str, *, repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root or Path.cwd()
    path = repo_root / BATCHES_DIR / batch_set_id / "batch_manifest.json"
    if not path.is_file():
        raise BatchBuildError(f"No batch manifest found at '{path}'.")
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return result


def load_batch(
    batch_set_id: str, batch_sequence: int, *, repo_root: Path | None = None
) -> pd.DataFrame:
    repo_root = repo_root or Path.cwd()
    path = repo_root / BATCHES_DIR / batch_set_id / "batches" / f"batch_{batch_sequence:02d}.csv"
    if not path.is_file():
        raise BatchBuildError(f"No batch file found at '{path}'.")
    return pd.read_csv(path)
