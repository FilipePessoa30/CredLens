"""Monitoring-detection acceptance gate (Phase 10B - Release Candidate
Acceptance Remediation).

`RC_1.0.0rc1_bc33e939` was declared `release_candidate_ready_with_
limitations` with a real `scenario_detection_rate` of 0.5 -
`credlens.release.manifest.decide_readiness` never read a detection
report at all (see `reports/release/release_errata.json`). This module
persists `credlens monitor evaluate-detection`/`evaluate-false-alerts`
evidence to disk (stamped with the current source-snapshot fingerprint,
same staleness-detection mechanism as `credlens.release.coverage_gate`)
and enforces the real acceptance floors against that persisted evidence -
never a number typed by hand into a CLI flag.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DETECTION_EVIDENCE_PATH = Path("reports/monitoring/detection_evaluation.json")
FALSE_ALERT_EVIDENCE_PATH = Path("reports/monitoring/false_alert_study.json")

BLOCKED_INPUT_RECALL_FLOOR = 1.0
RAW_DATA_QUALITY_DETECTION_FLOOR = 1.0
STRONG_DRIFT_DETECTION_FLOOR = 0.90
OVERALL_APPLICABLE_DETECTION_FLOOR = 0.90
BASELINE_HIGH_SEVERITY_CEILING = 0.0
BASELINE_MATERIAL_CEILING = 0.10


def write_detection_evidence(report_dict: dict[str, Any], *, repo_root: Path | None = None) -> Path:
    """Stamps `credlens.monitoring.detection_eval.DetectionEvaluationReport
    .to_dict()`'s output with the current source-snapshot fingerprint and
    persists it - the release validator reads THIS file, never re-running
    the evaluation itself (that stays a `slow`-marked, model-loading
    operation, not something a fast integrity check should trigger)."""
    from credlens.release.source_snapshot import compute_source_snapshot

    repo_root = repo_root or Path.cwd()
    snapshot = compute_source_snapshot(repo_root)
    payload = {
        **report_dict,
        "source_snapshot_fingerprint": snapshot.fingerprint,
        "measured_at_utc": datetime.now(UTC).isoformat(),
    }
    path = repo_root / DETECTION_EVIDENCE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_false_alert_evidence(
    report_dict: dict[str, Any], *, repo_root: Path | None = None
) -> Path:
    from credlens.release.source_snapshot import compute_source_snapshot

    repo_root = repo_root or Path.cwd()
    snapshot = compute_source_snapshot(repo_root)
    payload = {
        **report_dict,
        "source_snapshot_fingerprint": snapshot.fingerprint,
        "measured_at_utc": datetime.now(UTC).isoformat(),
    }
    path = repo_root / FALSE_ALERT_EVIDENCE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


@dataclass(frozen=True)
class MonitoringGateResult:
    status: str  # "pass" | "fail"
    detail: str


def _load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return result


def check_monitoring_detection_gate(*, repo_root: Path | None = None) -> MonitoringGateResult:
    from credlens.release.source_snapshot import compute_source_snapshot

    repo_root = repo_root or Path.cwd()
    detection = _load(repo_root / DETECTION_EVIDENCE_PATH)
    false_alerts = _load(repo_root / FALSE_ALERT_EVIDENCE_PATH)
    if detection is None or false_alerts is None:
        missing = [
            name
            for name, payload in (("detection", detection), ("false_alert", false_alerts))
            if payload is None
        ]
        return MonitoringGateResult(
            "fail",
            f"No {'/'.join(missing)} evidence found - run 'credlens monitor evaluate-detection' "
            "and 'credlens monitor evaluate-false-alerts' first.",
        )
    current = compute_source_snapshot(repo_root)
    stale = [
        name
        for name, payload in (("detection", detection), ("false_alert", false_alerts))
        if payload.get("source_snapshot_fingerprint") != current.fingerprint
    ]
    if stale:
        return MonitoringGateResult(
            "fail",
            f"{'/'.join(stale)} evidence is STALE (does not match the current source snapshot) - "
            "re-run 'credlens monitor evaluate-detection'/'evaluate-false-alerts'.",
        )

    failures = []
    if detection["blocked_input_recall"] < BLOCKED_INPUT_RECALL_FLOOR:
        failures.append(f"blocked_input_recall={detection['blocked_input_recall']:.2f} (< 1.00)")
    if detection["raw_data_quality_detection_rate"] < RAW_DATA_QUALITY_DETECTION_FLOOR:
        failures.append(
            "raw_data_quality_detection_rate="
            f"{detection['raw_data_quality_detection_rate']:.2f} (< 1.00)"
        )
    if detection["strong_drift_detection_rate"] < STRONG_DRIFT_DETECTION_FLOOR:
        failures.append(
            f"strong_drift_detection_rate={detection['strong_drift_detection_rate']:.2f} "
            f"(< {STRONG_DRIFT_DETECTION_FLOOR:.2f})"
        )
    if detection["overall_applicable_scenario_detection_rate"] < OVERALL_APPLICABLE_DETECTION_FLOOR:
        failures.append(
            "overall_applicable_scenario_detection_rate="
            f"{detection['overall_applicable_scenario_detection_rate']:.2f} "
            f"(< {OVERALL_APPLICABLE_DETECTION_FLOOR:.2f})"
        )
    if false_alerts["high_severity_false_alert_rate"] > BASELINE_HIGH_SEVERITY_CEILING:
        failures.append(
            "high_severity_false_alert_rate="
            f"{false_alerts['high_severity_false_alert_rate']:.2f} (> 0.00)"
        )
    if false_alerts["combined_material_false_alert_rate"] > BASELINE_MATERIAL_CEILING:
        failures.append(
            "combined_material_false_alert_rate="
            f"{false_alerts['combined_material_false_alert_rate']:.2f} "
            f"(> {BASELINE_MATERIAL_CEILING:.2f})"
        )
    if failures:
        return MonitoringGateResult("fail", "; ".join(failures))
    return MonitoringGateResult(
        "pass",
        "All monitoring-detection acceptance floors met: blocked_input_recall="
        f"{detection['blocked_input_recall']:.2f}, raw_data_quality_detection_rate="
        f"{detection['raw_data_quality_detection_rate']:.2f}, strong_drift_detection_rate="
        f"{detection['strong_drift_detection_rate']:.2f}, "
        "overall_applicable_scenario_detection_rate="
        f"{detection['overall_applicable_scenario_detection_rate']:.2f}, "
        f"high_severity_false_alert_rate={false_alerts['high_severity_false_alert_rate']:.2f}, "
        f"combined_material_false_alert_rate={false_alerts['combined_material_false_alert_rate']:.2f}.",
    )
