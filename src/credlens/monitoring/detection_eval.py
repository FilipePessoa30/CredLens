"""Phase 10 gate F/G - detection evaluation matrix.

For each of the 12 documented monitoring scenarios
(`config/monitoring/scenarios.yml`), compares a hand-documented EXPECTED
outcome (which category should fire, whether the batch should be
blocked) against what the recalibrated pipeline (per-feature signals +
family-wise-corrected feature-drift check + gate G/H's signal/alert/
incident hierarchy) actually detects on a fresh run.

Important, honestly-disclosed limitation: each of the 12 scenarios
appears in only ONE batch (this is a single monitoring run, not a
repeated stream), so gate H's persistence-based "high" severity almost
never has a genuine opportunity to fire from real repeated observation
of the SAME perturbation. Two DIFFERENT scenarios that happen to land in
ADJACENT batch_sequence numbers and the SAME category (e.g. batches 3-4,
both `feature_drift`) can still combine into an "incident" under the
consecutive-batch rule - this is flagged explicitly wherever it happens,
since it reflects batch-sequence adjacency, not genuine repeated
confirmation of one real drift event.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from credlens.monitoring.incidents import IncidentReport, build_incident_report

EXPECTED_OUTCOMES: dict[str, dict[str, Any]] = {
    "baseline_like": {
        "expected_category": "none",
        "should_detect": False,
        "should_block": False,
        "note_en": "Unperturbed - used to measure the false-alert rate, not to test detection.",
    },
    "missingness_drift": {
        "expected_category": "data_quality",
        "should_detect": True,
        "should_block": False,
        "note_en": "15% extra missingness injected into the most-recent delinquency column.",
    },
    "utilization_shift": {
        "expected_category": "feature_drift",
        "should_detect": True,
        "should_block": False,
        "note_en": "Bill amounts scaled 1.5x - expected PSI/feature-drift signal.",
    },
    "payment_reduction": {
        "expected_category": "feature_drift",
        "should_detect": True,
        "should_block": False,
        "note_en": "Payment amounts halved - expected PSI/feature-drift signal.",
    },
    "delinquency_worsening": {
        "expected_category": "feature_drift",
        "should_detect": True,
        "should_block": False,
        "note_en": "Delinquency status shifted by +1 step - expected PSI/feature-drift signal.",
    },
    "out_of_domain_codes": {
        "expected_category": "data_quality",
        "should_detect": True,
        "should_block": False,
        "note_en": "10% of delinquency-status values replaced with an out-of-domain code - "
        "quarantined by the strict input contract, not schema-blocked.",
    },
    "feature_range_violation": {
        "expected_category": "data_quality",
        "should_detect": True,
        "should_block": False,
        "note_en": "2% of bill amounts made implausibly large - range violation, quarantined.",
    },
    "prevalence_drift": {
        "expected_category": "score_drift",
        "should_detect": True,
        "should_block": False,
        "note_en": "Target prevalence resampled to 35% - expected score-distribution signal.",
    },
    "score_distribution_shift": {
        "expected_category": "feature_drift",
        "should_detect": True,
        "should_block": False,
        "note_en": "Combined bill-scale and delinquency-step shift - expected feature AND score "
        "drift; feature_drift is the primary category checked here.",
    },
    "subgroup_composition_shift": {
        "expected_category": "score_drift",
        "should_detect": True,
        "should_block": False,
        "note_en": "Age-bucket composition oversampled - expected subgroup/score-composition "
        "signal.",
    },
    "label_delay": {
        "expected_category": "none",
        "should_detect": False,
        "should_block": False,
        "note_en": "Labels pending - performance drift cannot be computed; must show "
        "insufficient_sample, never a high alert.",
    },
    "corrupted_schema": {
        "expected_category": "blocked_input",
        "should_detect": True,
        "should_block": True,
        "note_en": "A required column dropped - must be schema-blocked deterministically.",
    },
}


class DetectionEvalError(Exception):
    """Raised when a fresh monitoring run cannot be produced for detection evaluation."""


@dataclass(frozen=True)
class DetectionRow:
    scenario: str
    batch_sequence: int
    expected_category: str
    should_detect: bool
    should_block: bool
    detected: bool
    detected_category: str
    detected_severity: str
    actually_blocked: bool
    correctly_blocked: bool
    true_positive: bool
    false_positive: bool
    false_negative: bool
    incident_id: str | None
    note_en: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "batch_sequence": self.batch_sequence,
            "expected_category": self.expected_category,
            "should_detect": self.should_detect,
            "should_block": self.should_block,
            "detected": self.detected,
            "detected_category": self.detected_category,
            "detected_severity": self.detected_severity,
            "actually_blocked": self.actually_blocked,
            "correctly_blocked": self.correctly_blocked,
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "incident_id": self.incident_id,
            "note_en": self.note_en,
        }


@dataclass(frozen=True)
class DetectionEvaluationReport:
    reference_id: str
    run_id: str
    rows: list[DetectionRow]
    incident_report: IncidentReport

    @property
    def scenario_detection_rate(self) -> float:
        expected = [r for r in self.rows if r.should_detect]
        if not expected:
            return float("nan")
        return sum(1 for r in expected if r.true_positive) / len(expected)

    @property
    def false_alert_rate_on_non_perturbed_scenarios(self) -> float:
        non_perturbed = [r for r in self.rows if not r.should_detect]
        if not non_perturbed:
            return float("nan")
        return sum(1 for r in non_perturbed if r.false_positive) / len(non_perturbed)

    @property
    def blocked_input_recall(self) -> float:
        should_block = [r for r in self.rows if r.should_block]
        if not should_block:
            return float("nan")
        return sum(1 for r in should_block if r.correctly_blocked) / len(should_block)

    @property
    def severity_precision(self) -> float:
        """Of every row the pipeline marked `high`, the fraction where a
        genuine blocking violation or expected material event justified
        it - never an isolated marginal signal (gate H)."""
        high_rows = [r for r in self.rows if r.detected_severity == "high"]
        if not high_rows:
            return float("nan")
        justified = sum(1 for r in high_rows if r.should_block or r.should_detect)
        return justified / len(high_rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "run_id": self.run_id,
            "scenario_detection_rate": round(self.scenario_detection_rate, 4),
            "false_alert_rate_on_non_perturbed_scenarios": round(
                self.false_alert_rate_on_non_perturbed_scenarios, 4
            ),
            "blocked_input_recall": round(self.blocked_input_recall, 4),
            "severity_precision": round(self.severity_precision, 4),
            "alert_compression_ratio": (
                round(self.incident_report.alert_compression_ratio, 4)
                if self.incident_report.n_alert_groups
                else None
            ),
            "incident_compression_ratio": (
                round(self.incident_report.incident_compression_ratio, 4)
                if self.incident_report.n_incidents
                else None
            ),
            "rows": [r.to_dict() for r in self.rows],
        }


def run_detection_evaluation(
    reference_id: str, *, repo_root: Path | None = None
) -> DetectionEvaluationReport:
    repo_root = repo_root or Path.cwd()
    from credlens.monitoring.batches import load_batch_manifest
    from credlens.monitoring.reporting import run as run_monitoring_pipeline
    from credlens.monitoring.reporting import simulate_batches

    batch_set_id = f"BATCHSET_{reference_id}"
    try:
        load_batch_manifest(batch_set_id, repo_root=repo_root)
    except FileNotFoundError:
        simulate_batches(reference_id, repo_root=repo_root)

    run_id = run_monitoring_pipeline(reference_id, batch_set_id, repo_root=repo_root)
    incident_report = build_incident_report(run_id, repo_root=repo_root)

    from credlens.monitoring.runner import load_run

    run_record = load_run(run_id, repo_root=repo_root)

    groups_by_batch_category = {
        (g.batch_sequence, g.category): g for g in incident_report.alert_groups
    }
    incident_by_group_id = {
        alert_group_id: incident.incident_id
        for incident in incident_report.incidents
        for alert_group_id in incident.alert_group_ids
    }

    rows: list[DetectionRow] = []
    for batch in run_record["batches"]:
        scenario = batch["simulation_scenario"]
        expectation = EXPECTED_OUTCOMES.get(scenario)
        if expectation is None:
            continue
        batch_sequence = batch["batch_sequence"]
        actually_blocked = bool(batch["blocked"])

        matching_group = None
        if expectation["expected_category"] == "blocked_input":
            matching_group = next(
                (
                    g
                    for (bseq, _cat), g in groups_by_batch_category.items()
                    if bseq == batch_sequence and g.status == "blocked_input"
                ),
                None,
            )
        else:
            matching_group = groups_by_batch_category.get(
                (batch_sequence, expectation["expected_category"])
            )

        detected = matching_group is not None
        detected_category = matching_group.category if matching_group else "none"
        detected_severity = matching_group.severity if matching_group else "none"
        incident_id = (
            incident_by_group_id.get(matching_group.alert_group_id) if matching_group else None
        )

        should_detect = bool(expectation["should_detect"])
        true_positive = should_detect and detected
        false_positive = (not should_detect) and detected
        false_negative = should_detect and not detected

        rows.append(
            DetectionRow(
                scenario=scenario,
                batch_sequence=batch_sequence,
                expected_category=expectation["expected_category"],
                should_detect=should_detect,
                should_block=bool(expectation["should_block"]),
                detected=detected,
                detected_category=detected_category,
                detected_severity=detected_severity,
                actually_blocked=actually_blocked,
                correctly_blocked=actually_blocked == bool(expectation["should_block"]),
                true_positive=true_positive,
                false_positive=false_positive,
                false_negative=false_negative,
                incident_id=incident_id,
                note_en=str(expectation["note_en"]),
            )
        )

    return DetectionEvaluationReport(
        reference_id=reference_id, run_id=run_id, rows=rows, incident_report=incident_report
    )
