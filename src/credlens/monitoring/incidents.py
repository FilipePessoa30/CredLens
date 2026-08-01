"""Phase 10 gates G and H - Signal/Alert/Incident hierarchy and
recalibrated severity, built ON TOP OF the existing per-metric
`credlens.monitoring.alerts.Alert` records (Phase 9) WITHOUT renaming or
altering them.

Terminology mapping (gate G's own vocabulary, applied to this codebase):
  - "Signal" = exactly one existing `Alert` record (one metric crossing a
    threshold, in one batch) - unchanged, still written by
    `credlens.monitoring.runner`/`alerts.build_alert`.
  - "Alert" (gate G's sense - NOT `alerts.Alert`) = one or more RELATED
    signals in the SAME batch and category, represented here as
    `AlertGroup`. Reduces "3 separate PSI signals" to "1 feature-drift
    alert covering 3 features" while preserving every signal_id.
  - "Incident" = a CONFIRMED set of related alert-groups across
    CONSECUTIVE batches with a possible common cause, represented here
    as `Incident`. An isolated AlertGroup with no confirmation in the
    next batch stays an alert, never becomes an incident (Phase 10 gate
    G: "PSI isolado sem confirmação permanece um sinal").

Recalibrated severity (gate H) - "high" requires a COMBINATION, never an
isolated marginal metric:
  - `blocked_input` (schema integrity failure) -> always high, immediately
    (no confirmation needed - a corrupted schema is certain, not
    probabilistic).
  - `feature_drift` -> high only if the family-wise-calibrated
    `psi_family_wise` signal (see `credlens.monitoring.calibration_study`)
    fired AND the same category's AlertGroup recurs in the next
    `consecutive_batches_for_high_severity` batches.
  - `performance_drift` -> high only if `material_deviation` AND
    confirmed across consecutive batches (a single-batch AUC drop is
    never high on its own - Phase 10 gate H's explicit example).
  - `score_drift` -> same persistence rule as performance_drift.
  - Anything else (an isolated single marginal signal, unconfirmed) is
    at most `medium`, never `high`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from credlens.monitoring.alerts import load_alerts

INCIDENTS_DIR = Path("reports/monitoring/runs")

_DIAGNOSTIC_ACTIONS = {
    "data_quality": "Inspect quarantined rows and the batch schema before further scoring.",
    "feature_drift": "Compare the feature's histogram against the reference; check for an "
    "upstream data or process change.",
    "score_drift": "Inspect the risk-band distribution shift and the top-decile population.",
    "performance_drift": "Confirm labels are correctly joined; if it persists, flag for a full "
    "model_validation re-run.",
}


class IncidentBuildError(Exception):
    """Raised when the signal/alert/incident hierarchy cannot be built."""


@dataclass(frozen=True)
class AlertGroup:
    alert_group_id: str
    run_id: str
    batch_sequence: int
    category: str
    signal_ids: list[str]
    severity: str
    evidence: list[str]
    causal_hypothesis: str
    diagnostic_action: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_group_id": self.alert_group_id,
            "run_id": self.run_id,
            "batch_sequence": self.batch_sequence,
            "category": self.category,
            "signal_ids": self.signal_ids,
            "severity": self.severity,
            "evidence": self.evidence,
            "causal_hypothesis": self.causal_hypothesis,
            "diagnostic_action": self.diagnostic_action,
            "status": self.status,
        }


@dataclass(frozen=True)
class Incident:
    incident_id: str
    run_id: str
    batch_sequences: list[int]
    alert_group_ids: list[str]
    signal_ids: list[str]
    category: str
    severity: str
    aggregation_rule: str
    evidence: list[str]
    causal_hypothesis: str
    diagnostic_action: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "run_id": self.run_id,
            "batch_sequences": self.batch_sequences,
            "alert_group_ids": self.alert_group_ids,
            "signal_ids": self.signal_ids,
            "category": self.category,
            "severity": self.severity,
            "aggregation_rule": self.aggregation_rule,
            "evidence": self.evidence,
            "causal_hypothesis": self.causal_hypothesis,
            "diagnostic_action": self.diagnostic_action,
            "status": self.status,
        }


@dataclass(frozen=True)
class IncidentReport:
    run_id: str
    n_signals: int
    n_alert_groups: int
    n_incidents: int
    alert_groups: list[AlertGroup] = field(default_factory=list)
    incidents: list[Incident] = field(default_factory=list)

    @property
    def alert_compression_ratio(self) -> float:
        return self.n_signals / self.n_alert_groups if self.n_alert_groups else float("nan")

    @property
    def incident_compression_ratio(self) -> float:
        return self.n_signals / self.n_incidents if self.n_incidents else float("nan")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "n_signals": self.n_signals,
            "n_alert_groups": self.n_alert_groups,
            "n_incidents": self.n_incidents,
            "alert_compression_ratio": (
                round(self.alert_compression_ratio, 4) if self.n_alert_groups else None
            ),
            "incident_compression_ratio": (
                round(self.incident_compression_ratio, 4) if self.n_incidents else None
            ),
            "alert_groups": [g.to_dict() for g in self.alert_groups],
            "incidents": [i.to_dict() for i in self.incidents],
        }


def _has_family_wise_signal(signals: list[dict[str, Any]]) -> bool:
    return any(s["metric"].startswith("psi_family_wise__") for s in signals)


def _has_material_family_wise_signal(signals: list[dict[str, Any]]) -> bool:
    return any(
        s["metric"].startswith("psi_family_wise__") and s["status"] == "material_deviation"
        for s in signals
    )


def _group_severity(
    category: str, signals: list[dict[str, Any]], *, confirmed_next_batch: bool
) -> str:
    """Gate H's recalibrated severity - see module docstring for the
    full policy. Any `blocked_input` status signal is high immediately;
    everything else requires a combination of a PROPERLY CALIBRATED
    breadth/strength signal AND persistence (confirmed in the next
    batch) before reaching high.

    Deliberately NOT used as an escalation trigger: raw signal COUNT
    (`len(signals) >= 2`). An empirical check found ~2 marginal
    per-feature PSI signals co-occur in a genuinely unperturbed batch
    ~20% of the time (18 correlated per-feature checks each at their own
    ~5% marginal rate is not a rare coincidence) - an uncalibrated
    "2+ features fired" rule would itself reintroduce a false-alert
    problem at the AlertGroup level, exactly what gate F's family-wise
    threshold exists to prevent. `feature_drift` escalation therefore
    uses ONLY the family-wise-calibrated signal
    (`credlens.monitoring.calibration_study`); `performance_drift`/
    `score_drift` are single-metric categories with no multiple-
    comparisons problem, so their OWN marginal calibration is already
    trustworthy on its own."""
    if any(s["status"] == "blocked_input" for s in signals):
        return "high"
    if category == "feature_drift":
        if _has_material_family_wise_signal(signals) and confirmed_next_batch:
            return "high"
        if _has_family_wise_signal(signals):
            return "medium"
        return "low"
    if category in ("performance_drift", "score_drift"):
        material = any(s["status"] == "material_deviation" for s in signals)
        review = any(s["status"] == "review" for s in signals)
        if material and confirmed_next_batch:
            return "high"
        if material or review:
            return "medium"
        return "low"
    return "low"


def build_alert_groups(run_id: str, *, repo_root: Path | None = None) -> list[AlertGroup]:
    """Groups signals (existing `Alert` records) sharing the SAME
    (batch_sequence, category) into one AlertGroup, preserving every
    underlying signal_id - never discards a raw signal."""
    repo_root = repo_root or Path.cwd()
    signals = load_alerts(run_id, repo_root=repo_root)
    by_batch_category: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for signal in signals:
        key = (signal["batch_sequence"], signal["category"])
        by_batch_category.setdefault(key, []).append(signal)

    all_batch_sequences_with_category: dict[str, set[int]] = {}
    for (batch_sequence, category), _ in by_batch_category.items():
        all_batch_sequences_with_category.setdefault(category, set()).add(batch_sequence)

    groups: list[AlertGroup] = []
    for (batch_sequence, category), group_signals in sorted(by_batch_category.items()):
        confirmed_next = (batch_sequence + 1) in all_batch_sequences_with_category.get(
            category, set()
        )
        severity = _group_severity(category, group_signals, confirmed_next_batch=confirmed_next)
        groups.append(
            AlertGroup(
                alert_group_id=f"ALERTGROUP_{run_id}_{batch_sequence:02d}_{category}",
                run_id=run_id,
                batch_sequence=batch_sequence,
                category=category,
                signal_ids=[s["alert_id"] for s in group_signals],
                severity=severity,
                evidence=[s["evidence"] for s in group_signals],
                causal_hypothesis=(
                    f"{len(group_signals)} signal(s) in category '{category}' at batch "
                    f"{batch_sequence}."
                ),
                diagnostic_action=_DIAGNOSTIC_ACTIONS.get(category, "Investigate further."),
                status=(
                    "blocked_input"
                    if any(s["status"] == "blocked_input" for s in group_signals)
                    else severity
                ),
            )
        )
    return groups


def build_incidents(
    run_id: str, alert_groups: list[AlertGroup], *, confirmation_window: int = 2
) -> list[Incident]:
    """An incident is a run of >= `confirmation_window` CONSECUTIVE
    batches with an AlertGroup in the SAME category (consecutive-batch
    confirmation, Phase 10 gate F/G), OR any single `blocked_input`
    AlertGroup (a corrupted schema is certain on its own, never needs
    confirmation - Phase 10 gate G's explicit example)."""
    incidents: list[Incident] = []
    by_category: dict[str, list[AlertGroup]] = {}
    for group in alert_groups:
        by_category.setdefault(group.category, []).append(group)

    for category, groups in by_category.items():
        groups_sorted = sorted(groups, key=lambda g: g.batch_sequence)
        blocked = [g for g in groups_sorted if g.status == "blocked_input"]
        for group in blocked:
            incidents.append(
                Incident(
                    incident_id=f"INCIDENT_{run_id}_{category}_{group.batch_sequence:02d}_blocked",
                    run_id=run_id,
                    batch_sequences=[group.batch_sequence],
                    alert_group_ids=[group.alert_group_id],
                    signal_ids=list(group.signal_ids),
                    category=category,
                    severity="high",
                    aggregation_rule="blocking_schema_violation_never_needs_confirmation",
                    evidence=list(group.evidence),
                    causal_hypothesis="Corrupted/invalid input schema.",
                    diagnostic_action=_DIAGNOSTIC_ACTIONS.get(category, "Investigate further."),
                    status="blocked_input",
                )
            )

        # Only `medium`/`high` AlertGroups are eligible to form a
        # confirmation chain - an isolated `low`-severity group (a single
        # marginal per-feature signal with no family-wise/breadth
        # corroboration of its own) must NEVER count as one link of a
        # persistence chain. Without this filter, ordinary per-feature
        # false-alert noise (one marginal PSI signal in nearly every
        # batch, by design ~5% per feature) would trivially chain almost
        # every batch into one spurious "incident", exactly defeating the
        # purpose of requiring persistence (Phase 10 gate G: "PSI isolado
        # sem confirmação permanece um sinal").
        eligible = [g for g in groups_sorted if g.status != "blocked_input" and g.severity != "low"]
        run_members: list[AlertGroup] = []
        for group in eligible:
            if run_members and group.batch_sequence == run_members[-1].batch_sequence + 1:
                run_members.append(group)
            else:
                if len(run_members) >= confirmation_window:
                    incidents.append(_incident_from_run(run_id, category, run_members))
                run_members = [group]
        if len(run_members) >= confirmation_window:
            incidents.append(_incident_from_run(run_id, category, run_members))

    return incidents


def _incident_from_run(run_id: str, category: str, run_members: list[AlertGroup]) -> Incident:
    batch_sequences = [g.batch_sequence for g in run_members]
    severity = "high" if any(g.severity == "high" for g in run_members) else "medium"
    signal_ids = [sid for g in run_members for sid in g.signal_ids]
    return Incident(
        incident_id=(
            f"INCIDENT_{run_id}_{category}_{batch_sequences[0]:02d}_{batch_sequences[-1]:02d}"
        ),
        run_id=run_id,
        batch_sequences=batch_sequences,
        alert_group_ids=[g.alert_group_id for g in run_members],
        signal_ids=signal_ids,
        category=category,
        severity=severity,
        aggregation_rule=(
            f">= {len(run_members)} consecutive batches ({batch_sequences[0]}-"
            f"{batch_sequences[-1]}) with a '{category}' alert group"
        ),
        evidence=[e for g in run_members for e in g.evidence],
        causal_hypothesis=(
            f"Persistent '{category}' deviation across batches {batch_sequences[0]}-"
            f"{batch_sequences[-1]} - possible common upstream cause."
        ),
        diagnostic_action=_DIAGNOSTIC_ACTIONS.get(category, "Investigate further."),
        status=severity,
    )


def build_incident_report(
    run_id: str, *, confirmation_window: int | None = None, repo_root: Path | None = None
) -> IncidentReport:
    repo_root = repo_root or Path.cwd()
    signals = load_alerts(run_id, repo_root=repo_root)
    if confirmation_window is None:
        from credlens.monitoring.contracts import load_thresholds_config

        confirmation_window = int(
            load_thresholds_config(repo_root).multiple_comparisons[
                "consecutive_batches_for_incident"
            ]
        )
    alert_groups = build_alert_groups(run_id, repo_root=repo_root)
    incidents = build_incidents(run_id, alert_groups, confirmation_window=confirmation_window)
    return IncidentReport(
        run_id=run_id,
        n_signals=len(signals),
        n_alert_groups=len(alert_groups),
        n_incidents=len(incidents),
        alert_groups=alert_groups,
        incidents=incidents,
    )


def write_incident_report(report: IncidentReport, *, repo_root: Path | None = None) -> Path:
    repo_root = repo_root or Path.cwd()
    out_dir = repo_root / INCIDENTS_DIR / report.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "incidents.json"
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return path


def load_incident_report(run_id: str, *, repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root or Path.cwd()
    path = repo_root / INCIDENTS_DIR / run_id / "incidents.json"
    if not path.is_file():
        raise IncidentBuildError(f"No incident report found at '{path}'.")
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return result
