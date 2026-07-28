"""Shared fixtures for Phase 8 modeling/dashboard tests.

`tiny_uci_frame` is a small, fully synthetic DataFrame shaped exactly
like the real UCI benchmark (same column names/domains) - used for fast,
isolated unit tests of pure functions (feature engineering, splitting,
contracts, evaluation metrics) that do not need the real 30,000-row file.
Tests that need the REAL acquired benchmark (already on disk in this
repo, see docs/data_sources.md) call `credlens.modeling.data.
load_uci_default_credit` directly and are marked `@pytest.mark.slow`.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _make_tiny_uci_frame(n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    delinquency_signal = rng.integers(-2, 4, size=(n, 6)).astype(float)
    # Target correlated with the most recent delinquency status, keeping
    # both classes well represented for stratified 60/20/20 splitting.
    logit = 0.9 * delinquency_signal[:, 0] - 1.0
    prob = 1.0 / (1.0 + np.exp(-logit))
    y = (rng.random(n) < prob).astype(int)
    # Force a minimum count of positives so a 60/20/20 stratified split
    # never starves any partition of the minority class.
    min_positive = max(30, n // 5)
    if y.sum() < min_positive:
        flip_idx = rng.choice(np.flatnonzero(y == 0), size=min_positive - y.sum(), replace=False)
        y[flip_idx] = 1

    bill = rng.integers(-2000, 20000, size=(n, 6))
    payment = rng.integers(0, 8000, size=(n, 6))

    return pd.DataFrame(
        {
            "ID": np.arange(1, n + 1),
            "X1": rng.integers(10000, 300000, size=n),
            "X2": rng.integers(1, 3, size=n),
            "X3": rng.integers(1, 5, size=n),
            "X4": rng.integers(1, 4, size=n),
            "X5": rng.integers(21, 65, size=n),
            "X6": delinquency_signal[:, 0].astype(int),
            "X7": delinquency_signal[:, 1].astype(int),
            "X8": delinquency_signal[:, 2].astype(int),
            "X9": delinquency_signal[:, 3].astype(int),
            "X10": delinquency_signal[:, 4].astype(int),
            "X11": delinquency_signal[:, 5].astype(int),
            "X12": bill[:, 0],
            "X13": bill[:, 1],
            "X14": bill[:, 2],
            "X15": bill[:, 3],
            "X16": bill[:, 4],
            "X17": bill[:, 5],
            "X18": payment[:, 0],
            "X19": payment[:, 1],
            "X20": payment[:, 2],
            "X21": payment[:, 3],
            "X22": payment[:, 4],
            "X23": payment[:, 5],
            "Y": y,
        }
    )


@pytest.fixture
def tiny_uci_frame() -> pd.DataFrame:
    return _make_tiny_uci_frame(n=300, seed=0)


@pytest.fixture
def tiny_uci_frame_factory() -> Callable[..., pd.DataFrame]:
    return _make_tiny_uci_frame


_P9_EXPERIMENT_ID = "TEST_p9_base"
_P9_MODEL_ID = "TEST_p9_base_model"


@pytest.fixture(scope="module")
def phase9_isolated_repo_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real, isolated copy of the Phase 8/9 config + acquired UCI CSV,
    with the FULL modeling pipeline (train -> evaluate -> explain ->
    audit-groups -> stress-test -> register) already run once per test
    session, producing a real registered `candidate` model that
    `credlens.model_validation`/`credlens.monitoring` slow tests can
    validate/monitor without ever touching the real official experiment
    on disk (mirrors `tests/test_modeling_reporting.py`'s isolated-repo
    pattern, shared here so it is built only once for the whole session)."""
    real_root = Path.cwd()
    root = tmp_path_factory.mktemp("phase9_isolated_repo")

    for config_subdir in ("modeling", "model_validation", "monitoring"):
        src = real_root / "config" / config_subdir
        dst = root / "config" / config_subdir
        dst.mkdir(parents=True)
        for file in src.glob("*.yml"):
            shutil.copy(file, dst / file.name)

    metadata_dir = root / "data" / "metadata"
    metadata_dir.mkdir(parents=True)
    shutil.copy(
        real_root / "data" / "metadata" / "file_manifest.csv", metadata_dir / "file_manifest.csv"
    )
    raw_dir = root / "data" / "raw" / "uci_default_credit"
    raw_dir.mkdir(parents=True)
    shutil.copy(
        real_root / "data" / "raw" / "uci_default_credit" / "default_of_credit_card_clients.csv",
        raw_dir / "default_of_credit_card_clients.csv",
    )

    from credlens.modeling import reporting as modeling_reporting

    modeling_reporting.train_experiment(_P9_EXPERIMENT_ID, repo_root=root, seed=42)
    modeling_reporting.evaluate_experiment(_P9_EXPERIMENT_ID, repo_root=root)
    modeling_reporting.compare_models(_P9_EXPERIMENT_ID, repo_root=root)
    modeling_reporting.explain_experiment(_P9_EXPERIMENT_ID, repo_root=root)
    modeling_reporting.audit_groups_experiment(_P9_EXPERIMENT_ID, repo_root=root)
    modeling_reporting.stress_test_experiment(_P9_EXPERIMENT_ID, repo_root=root)
    modeling_reporting.register_experiment_model(_P9_EXPERIMENT_ID, _P9_MODEL_ID, repo_root=root)
    modeling_reporting.write_reports(_P9_EXPERIMENT_ID, _P9_MODEL_ID, repo_root=root)
    return root


@pytest.fixture(scope="session")
def phase9_experiment_id() -> str:
    return _P9_EXPERIMENT_ID


@pytest.fixture(scope="session")
def phase9_model_id() -> str:
    return _P9_MODEL_ID
