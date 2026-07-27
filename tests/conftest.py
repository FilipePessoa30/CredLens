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

from collections.abc import Callable

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
