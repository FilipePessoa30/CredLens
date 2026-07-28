"""Local, structured alerts (Phase 9 section 17) - never emailed, never
posted to Slack/a webhook, never acted on automatically. Every alert is a
plain dataclass written to a local JSON file; `credlens monitor alerts`
only reads it back.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from credlens.monitoring.thresholds import CalibratedThreshold, classify_state

_ALERT_COUNTER = {"n": 0}


def _next_alert_id(run_id: str) -> str:
    _ALERT_COUNTER["n"] += 1
    return f"ALERT_{run_id}_{_ALERT_COUNTER['n']:04d}"


@dataclass(frozen=True)
class Alert:
    alert_id: str
    monitoring_run: str
    batch_sequence: int
    model_id: str
    severity: str
    category: str
    metric: str
    reference_value: float
    observed_value: float
    threshold: float
    sample_size: int
    evidence: str
    recommended_diagnostic_action: str
    status: str
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "monitoring_run": self.monitoring_run,
            "batch_sequence": self.batch_sequence,
            "model_id": self.model_id,
            "severity": self.severity,
            "category": self.category,
            "metric": self.metric,
            "reference_value": round(self.reference_value, 6),
            "observed_value": round(self.observed_value, 6),
            "threshold": round(self.threshold, 6),
            "sample_size": self.sample_size,
            "evidence": self.evidence,
            "recommended_diagnostic_action": self.recommended_diagnostic_action,
            "status": self.status,
            "created_at_utc": self.created_at_utc,
        }


_DIAGNOSTIC_ACTIONS = {
    "data_quality": (
        "Inspect the quarantined rows and the batch's schema before any further scoring."
    ),
    "feature_drift": (
        "Compare the feature's histogram against the reference; check for an upstream "
        "data or process change."
    ),
    "score_drift": (
        "Inspect the risk-band distribution shift and the population above the top-10% "
        "operating point."
    ),
    "performance_drift": (
        "Confirm labels are correctly joined; if the shift persists across batches, "
        "flag for a full model_validation re-run."
    ),
}


def build_alert(
    *,
    run_id: str,
    batch_sequence: int,
    model_id: str,
    category: str,
    metric: str,
    reference_value: float,
    observed_value: float,
    calibrated: CalibratedThreshold,
    sample_size: int,
) -> Alert | None:
    """Returns `None` (no alert) when the observed deviation is within
    reference variability - only `review`/`material_deviation` produce an
    Alert record."""
    state = classify_state(abs(observed_value - reference_value), calibrated, sample_size)
    if state == "within_reference_variability":
        return None
    severity = "high" if state == "material_deviation" else "medium"
    return Alert(
        alert_id=_next_alert_id(run_id),
        monitoring_run=run_id,
        batch_sequence=batch_sequence,
        model_id=model_id,
        severity=severity,
        category=category,
        metric=metric,
        reference_value=reference_value,
        observed_value=observed_value,
        threshold=(
            calibrated.material_deviation_cutoff
            if state == "material_deviation"
            else calibrated.review_cutoff
        ),
        sample_size=sample_size,
        evidence=(
            f"|observed - reference| = {abs(observed_value - reference_value):.6f}, state={state}"
        ),
        recommended_diagnostic_action=_DIAGNOSTIC_ACTIONS.get(category, "Investigate further."),
        status=state,
    )


def build_blocked_input_alert(
    *, run_id: str, batch_sequence: int, model_id: str, detail: str
) -> Alert:
    return Alert(
        alert_id=_next_alert_id(run_id),
        monitoring_run=run_id,
        batch_sequence=batch_sequence,
        model_id=model_id,
        severity="high",
        category="data_quality",
        metric="schema_validity",
        reference_value=1.0,
        observed_value=0.0,
        threshold=1.0,
        sample_size=0,
        evidence=detail,
        recommended_diagnostic_action=_DIAGNOSTIC_ACTIONS["data_quality"],
        status="blocked_input",
    )


def write_alerts(run_id: str, alerts: list[Alert], *, repo_root: Path | None = None) -> Path:
    repo_root = repo_root or Path.cwd()
    out_dir = repo_root / "reports" / "monitoring" / "alerts"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run_id}.json"
    path.write_text(json.dumps([a.to_dict() for a in alerts], indent=2), encoding="utf-8")
    return path


def load_alerts(run_id: str, *, repo_root: Path | None = None) -> list[dict[str, Any]]:
    repo_root = repo_root or Path.cwd()
    path = repo_root / "reports" / "monitoring" / "alerts" / f"{run_id}.json"
    if not path.is_file():
        return []
    result: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return result
