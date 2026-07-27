"""Reproducible, stratified train/validation/test splitting (Phase 8
section 10).

The UCI benchmark has no usable time dimension - `ID` is an acquisition-
order artifact, not a timestamp - so this deliberately never claims an
"out-of-time" split. It uses a single documented protocol: stratified by
target, seed-controlled, with the test partition locked (by an ID-keyed
CSV, not just a re-derivable seed) the moment it is created, so later
pipeline-selection/tuning/calibration/threshold code can never touch it
before evaluation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.model_selection import train_test_split

from credlens.modeling.contracts import EvaluationConfig

SplitName = str  # "train" | "validation" | "test"


class SplitError(Exception):
    """Raised for split creation/loading/consistency failures."""


def _hash_ids(ids: pd.Series) -> str:
    joined = ",".join(str(i) for i in sorted(ids.tolist()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SplitManifest:
    split_version: str
    seed: int
    train_fraction: float
    validation_fraction: float
    test_fraction: float
    n_total: int
    n_train: int
    n_validation: int
    n_test: int
    train_prevalence: float
    validation_prevalence: float
    test_prevalence: float
    train_id_hash: str
    validation_id_hash: str
    test_id_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "split_version": self.split_version,
            "seed": self.seed,
            "train_fraction": self.train_fraction,
            "validation_fraction": self.validation_fraction,
            "test_fraction": self.test_fraction,
            "n_total": self.n_total,
            "n_train": self.n_train,
            "n_validation": self.n_validation,
            "n_test": self.n_test,
            "train_prevalence": round(self.train_prevalence, 6),
            "validation_prevalence": round(self.validation_prevalence, 6),
            "test_prevalence": round(self.test_prevalence, 6),
            "train_id_hash": self.train_id_hash,
            "validation_id_hash": self.validation_id_hash,
            "test_id_hash": self.test_id_hash,
        }


@dataclass(frozen=True)
class SplitAssignment:
    """Row indices (positional, into the ORIGINAL DataFrame passed to
    `create_split`) for each partition, plus the manifest describing them."""

    train_index: pd.Index
    validation_index: pd.Index
    test_index: pd.Index
    manifest: SplitManifest


def create_split(
    df: pd.DataFrame,
    *,
    id_column: str,
    target_column: str,
    config: EvaluationConfig,
    seed: int | None = None,
) -> SplitAssignment:
    """Stratified 60/20/20 (or whatever `config.split` declares) split.
    Test is carved out first and never touched again by anything in this
    module - `training.py`/`tuning.py`/`calibration.py`/`thresholds.py`
    only ever receive train/validation."""
    split_cfg = config.split
    seed = seed if seed is not None else int(split_cfg["seed"])
    train_frac = float(split_cfg["train_fraction"])
    val_frac = float(split_cfg["validation_fraction"])
    test_frac = float(split_cfg["test_fraction"])
    if abs((train_frac + val_frac + test_frac) - 1.0) > 1e-9:
        raise SplitError(
            f"Split fractions must sum to 1.0, got {train_frac} + {val_frac} + {test_frac}."
        )

    y = df[target_column]
    train_val_index, test_index = train_test_split(
        df.index,
        test_size=test_frac,
        random_state=seed,
        stratify=y,
    )
    remaining_val_frac = val_frac / (train_frac + val_frac)
    train_index, val_index = train_test_split(
        train_val_index,
        test_size=remaining_val_frac,
        random_state=seed,
        stratify=y.loc[train_val_index],
    )

    manifest = SplitManifest(
        split_version=config.config_version,
        seed=seed,
        train_fraction=train_frac,
        validation_fraction=val_frac,
        test_fraction=test_frac,
        n_total=len(df),
        n_train=len(train_index),
        n_validation=len(val_index),
        n_test=len(test_index),
        train_prevalence=float(y.loc[train_index].mean()),
        validation_prevalence=float(y.loc[val_index].mean()),
        test_prevalence=float(y.loc[test_index].mean()),
        train_id_hash=_hash_ids(df.loc[train_index, id_column]),
        validation_id_hash=_hash_ids(df.loc[val_index, id_column]),
        test_id_hash=_hash_ids(df.loc[test_index, id_column]),
    )
    return SplitAssignment(
        train_index=train_index,
        validation_index=val_index,
        test_index=test_index,
        manifest=manifest,
    )


def write_split_assignment_table(
    df: pd.DataFrame, assignment: SplitAssignment, *, id_column: str, path: Path
) -> None:
    """Writes an ID -> split-name CSV - the durable, ID-keyed record of
    exactly which rows are in which partition (Phase 8 section 10:
    "Crie um objeto ou manifest de split imutável"). This is the
    authoritative source for reloading a split, not re-derivation from
    the seed alone (sklearn's RNG stream is not a cross-version contract)."""
    rows = []
    for split_name, index in (
        ("train", assignment.train_index),
        ("validation", assignment.validation_index),
        ("test", assignment.test_index),
    ):
        for row_id in df.loc[index, id_column]:
            rows.append({"id": row_id, "split": split_name})
    table = pd.DataFrame(rows).sort_values("id").reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, index=False)


def load_split_assignment_table(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise SplitError(f"Split assignment table not found at '{path}'.")
    return pd.read_csv(path)


def apply_split_assignment_table(
    df: pd.DataFrame, table: pd.DataFrame, *, id_column: str
) -> SplitAssignment:
    """Rebuilds a `SplitAssignment` for `df` from a previously-written
    assignment table - the reproducibility path a re-run should prefer
    over blindly recomputing with the same seed."""
    merged = df[[id_column]].merge(table, left_on=id_column, right_on="id", how="left")
    if merged["split"].isna().any():
        raise SplitError("Some rows in df have no split assignment in the loaded table.")
    train_index = df.index[merged["split"].to_numpy() == "train"]
    val_index = df.index[merged["split"].to_numpy() == "validation"]
    test_index = df.index[merged["split"].to_numpy() == "test"]
    return SplitAssignment(
        train_index=train_index,
        validation_index=val_index,
        test_index=test_index,
        manifest=SplitManifest(
            split_version="loaded_from_table",
            seed=-1,
            train_fraction=len(train_index) / len(df),
            validation_fraction=len(val_index) / len(df),
            test_fraction=len(test_index) / len(df),
            n_total=len(df),
            n_train=len(train_index),
            n_validation=len(val_index),
            n_test=len(test_index),
            train_prevalence=float("nan"),
            validation_prevalence=float("nan"),
            test_prevalence=float("nan"),
            train_id_hash=_hash_ids(df.loc[train_index, id_column]),
            validation_id_hash=_hash_ids(df.loc[val_index, id_column]),
            test_id_hash=_hash_ids(df.loc[test_index, id_column]),
        ),
    )
