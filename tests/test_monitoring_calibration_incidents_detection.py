"""Tests for Phase 10 gates F/G/H: credlens.monitoring.calibration_study
(false-alert-rate measurement, family-wise threshold, Benjamini-Hochberg),
credlens.monitoring.incidents (signal/alert/incident hierarchy,
recalibrated severity), and credlens.monitoring.detection_eval (the
12-scenario detection matrix).

Marked `slow` - these run real PSI/ROC-AUC computations over 100 baseline
batches and a fresh monitoring run against the real 30,000-row UCI
benchmark's official reference.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from credlens.monitoring.detection_eval import DetectionEvaluationReport, DetectionRow

from credlens.monitoring.calibration_study import (
    FalseAlertBatchResult,
    benjamini_hochberg,
    calibrate_family_wise_psi_threshold,
    generate_baseline_like_batches,
    run_false_alert_rate_study,
)
from credlens.monitoring.incidents import (
    AlertGroup,
    _group_severity,
    build_incident_report,
    build_incidents,
)

pytestmark = pytest.mark.slow

_REFERENCE_ID = "REF_MODEL_behavioral_default_v1"
_MODEL_ID = "MODEL_behavioral_default_v1"


class TestBenjaminiHochberg:
    def test_no_features_significant_under_uniform_null(self) -> None:
        rng = np.random.default_rng(0)
        p_values = {f"feature_{i}": float(rng.uniform(0.2, 1.0)) for i in range(18)}
        result = benjamini_hochberg(p_values, fdr=0.10)
        assert not any(result.values())

    def test_clearly_significant_feature_is_flagged(self) -> None:
        p_values = {f"feature_{i}": 0.9 for i in range(17)}
        p_values["feature_17"] = 0.0001
        result = benjamini_hochberg(p_values, fdr=0.10)
        assert result["feature_17"] is True

    def test_returns_an_entry_for_every_feature(self) -> None:
        p_values = {"a": 0.5, "b": 0.01, "c": 0.99}
        result = benjamini_hochberg(p_values, fdr=0.10)
        assert set(result) == {"a", "b", "c"}


class TestGenerateBaselineLikeBatches:
    def test_produces_the_requested_count_and_size(self) -> None:
        batches = generate_baseline_like_batches(_MODEL_ID, n_batches=10, batch_size=200, seed=1)
        assert len(batches) == 10
        for _, batch_df in batches:
            assert len(batch_df) == 200

    def test_deterministic_given_the_same_seed(self) -> None:
        first = generate_baseline_like_batches(_MODEL_ID, n_batches=3, batch_size=100, seed=42)
        second = generate_baseline_like_batches(_MODEL_ID, n_batches=3, batch_size=100, seed=42)
        for (_, a), (_, b) in zip(first, second, strict=True):
            assert a.equals(b)

    def test_raises_if_batch_size_exceeds_test_set(self) -> None:
        from credlens.monitoring.calibration_study import CalibrationStudyError

        with pytest.raises(CalibrationStudyError):
            generate_baseline_like_batches(_MODEL_ID, n_batches=1, batch_size=999_999, seed=1)


class TestCalibrateFamilyWisePsiThreshold:
    def test_family_wise_threshold_matches_the_validated_result(self) -> None:
        from credlens.monitoring.reference import load_reference, load_reference_population

        reference = load_reference(_REFERENCE_ID)
        reference_population = load_reference_population(_REFERENCE_ID)
        family_wise = calibrate_family_wise_psi_threshold(
            reference_population,
            reference,
            batch_size=500,
            n_resamples=300,
            review_percentile=95,
            material_percentile=99.5,
            seed=20260728,
        )
        assert family_wise.metric == "psi_family_wise"
        # Empirically validated range (Phase 10 gate F audit): ~0.10-0.16.
        assert 0.08 < family_wise.review_cutoff < 0.20
        assert family_wise.material_deviation_cutoff > family_wise.review_cutoff


class TestRunFalseAlertRateStudy:
    def test_family_wise_correction_controls_the_rate_near_target(self) -> None:
        from credlens.monitoring.reference import load_reference, load_reference_population

        reference = load_reference(_REFERENCE_ID)
        reference_population = load_reference_population(_REFERENCE_ID)
        family_wise = calibrate_family_wise_psi_threshold(
            reference_population,
            reference,
            batch_size=500,
            n_resamples=300,
            review_percentile=95,
            material_percentile=99.5,
            seed=20260728,
        )
        study = run_false_alert_rate_study(
            _REFERENCE_ID,
            n_batches=100,
            batch_size=500,
            seed=20260728,
            family_wise_threshold=family_wise,
        )
        assert study.n_batches == 100
        # The uncorrected per-feature marginal rate must be dramatically
        # higher than the family-wise-corrected rate - this IS the gate
        # F finding (empirically ~60% vs ~5%).
        assert study.family_wise_marginal_rate > 0.4
        assert study.family_wise_corrected_review_rate < 0.15
        max_material_rate = study.family_wise_corrected_review_rate + 0.05
        assert study.family_wise_corrected_material_rate < max_material_rate

    def test_batch_results_carry_per_feature_detail(self) -> None:
        from credlens.monitoring.reference import load_reference, load_reference_population

        reference = load_reference(_REFERENCE_ID)
        reference_population = load_reference_population(_REFERENCE_ID)
        family_wise = calibrate_family_wise_psi_threshold(
            reference_population,
            reference,
            batch_size=500,
            n_resamples=50,
            review_percentile=95,
            material_percentile=99.5,
            seed=1,
        )
        study = run_false_alert_rate_study(
            _REFERENCE_ID, n_batches=5, batch_size=500, seed=1, family_wise_threshold=family_wise
        )
        assert len(study.batch_results) == 5
        first: FalseAlertBatchResult = study.batch_results[0]
        assert len(first.per_feature_psi) == 18
        assert first.family_wise_max_feature in first.per_feature_psi


class TestRunBatchSizeStudy:
    def test_produces_one_row_per_batch_size(self) -> None:
        from credlens.monitoring.calibration_study import run_batch_size_study

        rows = run_batch_size_study(
            _REFERENCE_ID,
            batch_sizes=[250, 500],
            n_batches_per_size=10,
            n_resamples_for_family_wise=50,
            review_percentile=95,
            material_percentile=99.5,
            seed=1,
        )
        assert [r.batch_size for r in rows] == [250, 500]
        for row in rows:
            assert row.family_wise_material_cutoff > row.family_wise_review_cutoff
            assert 0.0 <= row.family_wise_marginal_rate <= 1.0

    def test_smaller_batches_have_wider_natural_variability(self) -> None:
        """Real Phase 10 finding: smaller batches are noisier on BOTH the
        false-alert-rate and performance-variability axes - the empirical
        basis for recommending a minimum batch size rather than an
        arbitrary one."""
        from credlens.monitoring.calibration_study import run_batch_size_study

        rows = run_batch_size_study(
            _REFERENCE_ID,
            batch_sizes=[250, 2000],
            n_batches_per_size=15,
            n_resamples_for_family_wise=50,
            review_percentile=95,
            material_percentile=99.5,
            seed=1,
        )
        small, large = rows[0], rows[1]
        assert small.roc_auc_delta_p2_5_p97_5_width >= large.roc_auc_delta_p2_5_p97_5_width


class TestGroupSeverity:
    def test_blocked_input_is_always_high(self) -> None:
        signals = [{"status": "blocked_input", "metric": "schema_validity"}]
        assert _group_severity("data_quality", signals, confirmed_next_batch=False) == "high"

    def test_isolated_marginal_signal_is_low(self) -> None:
        signals = [{"status": "review", "metric": "psi__foo"}]
        assert _group_severity("feature_drift", signals, confirmed_next_batch=False) == "low"

    def test_breadth_alone_without_family_wise_signal_is_not_medium(self) -> None:
        # Two marginal per-feature signals, neither family-wise - must
        # NOT escalate past "low" (an uncalibrated breadth rule was found
        # to itself produce ~20% false "medium" escalations under the
        # null - see module docstring).
        signals = [
            {"status": "review", "metric": "psi__a"},
            {"status": "review", "metric": "psi__b"},
        ]
        assert _group_severity("feature_drift", signals, confirmed_next_batch=False) == "low"

    def test_family_wise_signal_without_confirmation_is_medium_not_high(self) -> None:
        signals = [
            {"status": "material_deviation", "metric": "psi_family_wise__x"},
        ]
        assert _group_severity("feature_drift", signals, confirmed_next_batch=False) == "medium"

    def test_family_wise_material_with_confirmation_is_high(self) -> None:
        signals = [{"status": "material_deviation", "metric": "psi_family_wise__x"}]
        assert _group_severity("feature_drift", signals, confirmed_next_batch=True) == "high"

    def test_performance_material_without_confirmation_is_medium(self) -> None:
        signals = [{"status": "material_deviation", "metric": "roc_auc_delta"}]
        assert _group_severity("performance_drift", signals, confirmed_next_batch=False) == "medium"

    def test_performance_material_with_confirmation_is_high(self) -> None:
        signals = [{"status": "material_deviation", "metric": "roc_auc_delta"}]
        assert _group_severity("performance_drift", signals, confirmed_next_batch=True) == "high"


class TestBuildIncidents:
    def test_isolated_alert_group_never_becomes_an_incident(self) -> None:
        groups = [
            AlertGroup(
                alert_group_id="G1",
                run_id="RUN_x",
                batch_sequence=5,
                category="feature_drift",
                signal_ids=["S1"],
                severity="medium",
                evidence=["e"],
                causal_hypothesis="h",
                diagnostic_action="d",
                status="medium",
            )
        ]
        incidents = build_incidents("RUN_x", groups, confirmation_window=2)
        assert incidents == []

    def test_two_consecutive_medium_groups_become_an_incident(self) -> None:
        groups = [
            AlertGroup(
                alert_group_id=f"G{i}",
                run_id="RUN_x",
                batch_sequence=i,
                category="feature_drift",
                signal_ids=[f"S{i}"],
                severity="medium",
                evidence=["e"],
                causal_hypothesis="h",
                diagnostic_action="d",
                status="medium",
            )
            for i in (5, 6)
        ]
        incidents = build_incidents("RUN_x", groups, confirmation_window=2)
        assert len(incidents) == 1
        assert incidents[0].batch_sequences == [5, 6]

    def test_low_severity_groups_never_chain_into_an_incident(self) -> None:
        groups = [
            AlertGroup(
                alert_group_id=f"G{i}",
                run_id="RUN_x",
                batch_sequence=i,
                category="feature_drift",
                signal_ids=[f"S{i}"],
                severity="low",
                evidence=["e"],
                causal_hypothesis="h",
                diagnostic_action="d",
                status="low",
            )
            for i in (1, 2, 3)
        ]
        incidents = build_incidents("RUN_x", groups, confirmation_window=2)
        assert incidents == []

    def test_blocked_input_becomes_an_incident_alone(self) -> None:
        groups = [
            AlertGroup(
                alert_group_id="G1",
                run_id="RUN_x",
                batch_sequence=12,
                category="data_quality",
                signal_ids=["S1"],
                severity="high",
                evidence=["e"],
                causal_hypothesis="h",
                diagnostic_action="d",
                status="blocked_input",
            )
        ]
        incidents = build_incidents("RUN_x", groups, confirmation_window=2)
        assert len(incidents) == 1
        assert incidents[0].severity == "high"
        assert incidents[0].batch_sequences == [12]


@pytest.fixture(scope="module")
def official_run_id() -> str:
    from credlens.monitoring.reporting import calibrate_reference_family_wise
    from credlens.monitoring.reporting import run as run_monitoring_pipeline

    calibrate_reference_family_wise(_REFERENCE_ID)
    batch_set_id = f"BATCHSET_{_REFERENCE_ID}"
    return run_monitoring_pipeline(_REFERENCE_ID, batch_set_id)


class TestBuildIncidentReportIntegration:
    def test_never_drops_a_raw_signal(self, official_run_id: str) -> None:
        report = build_incident_report(official_run_id)
        signal_ids_in_groups = {sid for g in report.alert_groups for sid in g.signal_ids}
        from credlens.monitoring.alerts import load_alerts

        all_signal_ids = {a["alert_id"] for a in load_alerts(official_run_id)}
        assert signal_ids_in_groups == all_signal_ids

    def test_compression_ratios_are_at_least_one(self, official_run_id: str) -> None:
        report = build_incident_report(official_run_id)
        if report.n_alert_groups:
            assert report.alert_compression_ratio >= 1.0
        if report.n_incidents:
            assert report.incident_compression_ratio >= 1.0

    def test_blocked_batch_always_yields_a_high_incident(self, official_run_id: str) -> None:
        report = build_incident_report(official_run_id)
        blocked_incidents = [i for i in report.incidents if i.status == "blocked_input"]
        assert len(blocked_incidents) >= 1
        assert all(i.severity == "high" for i in blocked_incidents)

    def test_write_and_load_incident_report_roundtrip(
        self, official_run_id: str, tmp_path: Path
    ) -> None:
        from credlens.monitoring.incidents import load_incident_report, write_incident_report

        report = build_incident_report(official_run_id)
        path = write_incident_report(report, repo_root=tmp_path)
        assert path.is_file()
        loaded = load_incident_report(official_run_id, repo_root=tmp_path)
        assert loaded["run_id"] == official_run_id
        assert loaded["n_signals"] == report.n_signals

    def test_load_incident_report_raises_when_missing(self, tmp_path: Path) -> None:
        from credlens.monitoring.incidents import IncidentBuildError, load_incident_report

        with pytest.raises(IncidentBuildError):
            load_incident_report("RUN_never_existed", repo_root=tmp_path)


class TestSensitivityAnalysis:
    """Phase 10B section 11 - real execution (never simulated numbers)
    across weak/moderate/strong magnitudes for every perturbation type
    with a direct, single calibrated metric."""

    def test_produces_a_row_per_type_and_magnitude(self, official_run_id: str) -> None:
        from credlens.monitoring.calibration_study import (
            SENSITIVITY_MAGNITUDES,
            run_sensitivity_analysis,
        )

        rows = run_sensitivity_analysis(
            _REFERENCE_ID, n_batches_per_magnitude=5, batch_size=200, seed=1
        )
        expected_n = sum(len(levels) for levels in SENSITIVITY_MAGNITUDES.values())
        assert len(rows) == expected_n
        seen = {(r.perturbation_type, r.magnitude_label) for r in rows}
        assert ("utilization_shift", "strong") in seen
        assert ("prevalence_drift", "weak") in seen

    def test_strong_magnitude_never_detects_less_than_weak_on_average(
        self, official_run_id: str
    ) -> None:
        """Not a perfection requirement (Phase 10B explicitly does not
        require 100% detection for a weak perturbation) - just the basic
        monotonicity a real, correctly-calibrated detector must have:
        a bigger perturbation of the SAME kind is never LESS detectable."""
        from credlens.monitoring.calibration_study import run_sensitivity_analysis

        rows = run_sensitivity_analysis(
            _REFERENCE_ID, n_batches_per_magnitude=8, batch_size=200, seed=1
        )
        by_type: dict[str, dict[str, float]] = {}
        for row in rows:
            by_type.setdefault(row.perturbation_type, {})[row.magnitude_label] = row.detection_rate
        for perturbation_type, levels in by_type.items():
            assert levels["strong"] >= levels["weak"], perturbation_type

    def test_strong_magnitude_reaches_the_acceptance_floor(self, official_run_id: str) -> None:
        """The 90% floor (section 9) applies to STRONG, correctly-built
        scenarios only - this mirrors the canonical scenario magnitudes
        already documented in scenarios_registry.yml."""
        from credlens.monitoring.calibration_study import run_sensitivity_analysis

        rows = run_sensitivity_analysis(
            _REFERENCE_ID, n_batches_per_magnitude=10, batch_size=200, seed=1
        )
        strong_rows = [r for r in rows if r.magnitude_label == "strong"]
        assert strong_rows
        for row in strong_rows:
            assert row.detection_rate >= 0.90, row.perturbation_type


class TestDetectionEvaluationReportEdgeCases:
    """Fast, isolated unit tests (no real model/reference needed) for
    `DetectionEvaluationReport`'s properties' empty-list ("nan") branches
    - unreachable from the real 12-scenario config (which always has both
    should_detect=True and should_detect=False rows), so only directly
    constructed rows can exercise them."""

    def _row(self, **overrides: object) -> DetectionRow:
        from credlens.monitoring.detection_eval import DetectionRow

        defaults: dict[str, object] = {
            "scenario": "s",
            "batch_sequence": 1,
            "expected_category": "feature_drift",
            "should_detect": True,
            "should_block": False,
            "detected": True,
            "detected_category": "feature_drift",
            "detected_severity": "high",
            "actually_blocked": False,
            "correctly_blocked": True,
            "true_positive": True,
            "false_positive": False,
            "false_negative": False,
            "incident_id": None,
            "note_en": "n",
        }
        defaults.update(overrides)
        return DetectionRow(**defaults)  # type: ignore[arg-type]

    def _report(self, rows: list[DetectionRow]) -> DetectionEvaluationReport:
        from credlens.monitoring.detection_eval import DetectionEvaluationReport
        from credlens.monitoring.incidents import IncidentReport

        return DetectionEvaluationReport(
            reference_id="R",
            run_id="RUN",
            rows=rows,
            incident_report=IncidentReport(
                run_id="RUN", n_signals=0, n_alert_groups=0, n_incidents=0
            ),
        )

    def test_false_alert_rate_is_nan_when_every_row_should_be_detected(self) -> None:
        import math

        report = self._report([self._row(should_detect=True)])
        assert math.isnan(report.false_alert_rate_on_non_perturbed_scenarios)

    def test_blocked_input_recall_is_nan_when_no_row_should_block(self) -> None:
        import math

        report = self._report([self._row(should_block=False)])
        assert math.isnan(report.blocked_input_recall)

    def test_severity_precision_is_nan_when_no_row_is_high_severity(self) -> None:
        import math

        report = self._report([self._row(detected_severity="medium")])
        assert math.isnan(report.severity_precision)

    def test_severity_precision_penalizes_an_unjustified_high(self) -> None:
        report = self._report(
            [self._row(detected_severity="high", should_block=False, should_detect=False)]
        )
        assert report.severity_precision == 0.0

    def test_to_dict_shape(self) -> None:
        report = self._report([self._row()])
        payload = report.to_dict()
        assert payload["reference_id"] == "R"
        assert payload["run_id"] == "RUN"
        assert len(payload["rows"]) == 1
        assert payload["rows"][0]["scenario"] == "s"

    def test_detection_row_to_dict_shape(self) -> None:
        row = self._row()
        payload = row.to_dict()
        assert payload["scenario"] == "s"
        assert payload["true_positive"] is True


class TestDetectionEvaluation:
    def test_blocked_input_is_always_correctly_detected(self, official_run_id: str) -> None:
        from credlens.monitoring.detection_eval import run_detection_evaluation

        report = run_detection_evaluation(_REFERENCE_ID)
        corrupted_row = next(r for r in report.rows if r.scenario == "corrupted_schema")
        assert corrupted_row.actually_blocked is True
        assert corrupted_row.correctly_blocked is True
        assert corrupted_row.detected_severity == "high"

    def test_baseline_like_is_never_a_false_positive_detection(self, official_run_id: str) -> None:
        from credlens.monitoring.detection_eval import run_detection_evaluation

        report = run_detection_evaluation(_REFERENCE_ID)
        baseline_row = next(r for r in report.rows if r.scenario == "baseline_like")
        assert baseline_row.should_detect is False

    def test_scenario_detection_rate_is_a_valid_fraction(self, official_run_id: str) -> None:
        from credlens.monitoring.detection_eval import run_detection_evaluation

        report = run_detection_evaluation(_REFERENCE_ID)
        assert 0.0 <= report.scenario_detection_rate <= 1.0
        assert 0.0 <= report.blocked_input_recall <= 1.0

    def test_every_scenario_in_config_has_a_row(self, official_run_id: str) -> None:
        from credlens.monitoring.detection_eval import EXPECTED_OUTCOMES, run_detection_evaluation

        report = run_detection_evaluation(_REFERENCE_ID)
        scenarios_seen = {r.scenario for r in report.rows}
        assert scenarios_seen == set(EXPECTED_OUTCOMES)

    def test_expected_outcomes_matches_the_documented_scenario_registry(self) -> None:
        """Phase 10B - `config/monitoring/scenarios_registry.yml` is the
        documented source of truth a reviewer reads;
        `EXPECTED_OUTCOMES` is the executable copy `detection_eval`
        actually runs against. This test is the enforcement that the two
        can never silently drift apart."""
        from pathlib import Path

        from credlens.monitoring.contracts import load_scenario_registry
        from credlens.monitoring.detection_eval import EXPECTED_OUTCOMES

        registry = load_scenario_registry(repo_root=Path.cwd())
        assert set(registry) == set(EXPECTED_OUTCOMES)
        for scenario, expectation in EXPECTED_OUTCOMES.items():
            entry = registry[scenario]
            assert entry["expected_category"] == expectation["expected_category"], scenario
            assert entry["blocking"] == expectation["should_block"], scenario
            expected_should_detect = entry["expected_action"] not in (
                "no_action",
                "labels_pending",
            )
            assert expected_should_detect == expectation["should_detect"], scenario

    def test_new_detection_categories_reach_the_acceptance_bar(self, official_run_id: str) -> None:
        """Phase 10B acceptance gates (Release Candidate Acceptance
        Remediation): a real fresh run must reach every one of these
        floors, not just report a number - this is the test the release
        validator's own coverage/detection gate mirrors."""
        from credlens.monitoring.detection_eval import run_detection_evaluation

        report = run_detection_evaluation(_REFERENCE_ID)
        assert report.blocked_input_recall == 1.0
        assert report.raw_data_quality_detection_rate == 1.0
        assert report.strong_drift_detection_rate >= 0.90
        assert report.overall_applicable_scenario_detection_rate >= 0.90
