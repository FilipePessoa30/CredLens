"""Tests for credlens.monitoring.thresholds/alerts (Phase 9 sections 16,
17) - fast, pure-function/small-DataFrame tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from credlens.monitoring.alerts import (
    build_alert,
    build_blocked_input_alert,
    load_alerts,
    write_alerts,
)
from credlens.monitoring.thresholds import CalibratedThreshold, calibrate_thresholds, classify_state


class _FakeThresholdsConfig:
    def __init__(self) -> None:
        self.raw = {
            "calibration": {
                "review_percentile": 95,
                "material_deviation_percentile": 99.5,
                "min_sample_size_for_alert": 30,
            }
        }

    @property
    def calibration(self) -> dict[str, Any]:
        return self.raw["calibration"]


class TestCalibrateThresholds:
    def test_calibrates_a_threshold_per_metric(self) -> None:
        rng = np.random.default_rng(0)
        n = 2000
        population = pd.DataFrame(
            {
                "feat_a": rng.normal(size=n),
                "score": rng.uniform(size=n),
                "y_true": rng.integers(0, 2, size=n),
            }
        )
        feature_stats = {
            "feat_a": {
                "histogram": {"bin_edges": list(np.histogram(population["feat_a"], bins=10)[1])}
            }
        }
        thresholds = calibrate_thresholds(
            population,
            feature_stats,
            _FakeThresholdsConfig(),
            batch_size=200,
            feature_columns=["feat_a"],
            n_resamples=30,
            seed=1,
        )
        assert "psi" in thresholds
        assert thresholds["psi"].material_deviation_cutoff >= thresholds["psi"].review_cutoff

    def test_write_and_load_calibrated_thresholds(self, tmp_path: Path) -> None:
        from credlens.monitoring.thresholds import (
            load_calibrated_thresholds,
            write_calibrated_thresholds,
        )

        thresholds = {
            "psi": CalibratedThreshold(
                metric="psi",
                review_cutoff=0.05,
                material_deviation_cutoff=0.1,
                n_resamples=100,
                batch_size=500,
                min_sample_size_for_alert=30,
            )
        }
        write_calibrated_thresholds("REF_x", thresholds, repo_root=tmp_path)
        loaded = load_calibrated_thresholds("REF_x", repo_root=tmp_path)
        assert loaded["psi"].review_cutoff == 0.05


class TestClassifyState:
    def test_within_variability_below_review_cutoff(self) -> None:
        calibrated = CalibratedThreshold("psi", 0.05, 0.1, 100, 500, 30)
        assert classify_state(0.02, calibrated, n_sample=500) == "within_reference_variability"

    def test_review_between_cutoffs(self) -> None:
        calibrated = CalibratedThreshold("psi", 0.05, 0.1, 100, 500, 30)
        assert classify_state(0.07, calibrated, n_sample=500) == "review"

    def test_material_deviation_above_material_cutoff(self) -> None:
        calibrated = CalibratedThreshold("psi", 0.05, 0.1, 100, 500, 30)
        assert classify_state(0.15, calibrated, n_sample=500) == "material_deviation"

    def test_small_sample_never_alerts(self) -> None:
        calibrated = CalibratedThreshold("psi", 0.05, 0.1, 100, 500, 30)
        assert classify_state(0.5, calibrated, n_sample=5) == "within_reference_variability"


class TestAlerts:
    def test_build_alert_returns_none_when_within_variability(self) -> None:
        calibrated = CalibratedThreshold("psi", 0.05, 0.1, 100, 500, 30)
        alert = build_alert(
            run_id="RUN_1",
            batch_sequence=1,
            model_id="M1",
            category="feature_drift",
            metric="psi__a",
            reference_value=0.0,
            observed_value=0.01,
            calibrated=calibrated,
            sample_size=500,
        )
        assert alert is None

    def test_build_alert_returns_alert_when_material(self) -> None:
        calibrated = CalibratedThreshold("psi", 0.05, 0.1, 100, 500, 30)
        alert = build_alert(
            run_id="RUN_1",
            batch_sequence=2,
            model_id="M1",
            category="feature_drift",
            metric="psi__a",
            reference_value=0.0,
            observed_value=0.2,
            calibrated=calibrated,
            sample_size=500,
        )
        assert alert is not None
        assert alert.severity == "high"
        assert alert.status == "material_deviation"

    def test_alert_never_contains_external_transport_fields(self) -> None:
        calibrated = CalibratedThreshold("psi", 0.05, 0.1, 100, 500, 30)
        alert = build_alert(
            run_id="RUN_1",
            batch_sequence=2,
            model_id="M1",
            category="feature_drift",
            metric="psi__a",
            reference_value=0.0,
            observed_value=0.2,
            calibrated=calibrated,
            sample_size=500,
        )
        assert alert is not None
        keys = alert.to_dict().keys()
        assert not any(k in keys for k in ("email", "slack_channel", "webhook_url"))

    def test_blocked_input_alert_is_always_high_severity(self) -> None:
        alert = build_blocked_input_alert(
            run_id="RUN_1", batch_sequence=12, model_id="M1", detail="missing X6"
        )
        assert alert.severity == "high"
        assert alert.status == "blocked_input"

    def test_write_and_load_alerts_roundtrip(self, tmp_path: Path) -> None:
        calibrated = CalibratedThreshold("psi", 0.05, 0.1, 100, 500, 30)
        alert = build_alert(
            run_id="RUN_1",
            batch_sequence=1,
            model_id="M1",
            category="feature_drift",
            metric="psi__a",
            reference_value=0.0,
            observed_value=0.2,
            calibrated=calibrated,
            sample_size=500,
        )
        assert alert is not None
        write_alerts("RUN_1", [alert], repo_root=tmp_path)
        loaded = load_alerts("RUN_1", repo_root=tmp_path)
        assert len(loaded) == 1

    def test_load_alerts_missing_run_returns_empty_list(self, tmp_path: Path) -> None:
        assert load_alerts("RUN_never", repo_root=tmp_path) == []
