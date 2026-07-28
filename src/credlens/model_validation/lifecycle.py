"""Explicit model lifecycle states (Phase 9 section 18).

Deliberately excludes `production`/`deployed`/`automatically_promoted` -
those states do not exist anywhere in this codebase's vocabulary. A
validation run may RECOMMEND a state (`validation_passed`,
`validation_passed_with_limitations`, `validation_failed`), but nothing
in this package writes that recommendation back as if it were an
automatic promotion - the lifecycle history is an append-only log a human
reads, not a state machine that acts on its own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

LifecycleState = Literal[
    "experiment",
    "candidate",
    "challenger",
    "validation_passed",
    "validation_passed_with_limitations",
    "validation_failed",
    "retired",
]

_ALLOWED_STATES: frozenset[str] = frozenset(
    {
        "experiment",
        "candidate",
        "challenger",
        "validation_passed",
        "validation_passed_with_limitations",
        "validation_failed",
        "retired",
    }
)

# Forbidden vocabulary - if any of these ever appear as a target state,
# `record_transition` refuses outright rather than silently accepting it.
_FORBIDDEN_STATES = frozenset({"production", "deployed", "automatically_promoted", "champion"})

LIFECYCLE_DIR = Path("reports/model_validation/lifecycle")


class LifecycleError(Exception):
    """Raised for an invalid or forbidden lifecycle transition."""


@dataclass(frozen=True)
class LifecycleTransition:
    from_state: str
    to_state: str
    evidence_ref: str
    gate_summary: str
    triggered_by: str
    timestamp_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_state": self.from_state,
            "to_state": self.to_state,
            "evidence_ref": self.evidence_ref,
            "gate_summary": self.gate_summary,
            "triggered_by": self.triggered_by,
            "timestamp_utc": self.timestamp_utc,
        }


@dataclass(frozen=True)
class LifecycleHistory:
    subject_id: str
    transitions: list[LifecycleTransition]

    @property
    def current_state(self) -> str:
        if not self.transitions:
            return "experiment"
        return self.transitions[-1].to_state

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "current_state": self.current_state,
            "transitions": [t.to_dict() for t in self.transitions],
        }


def load_lifecycle_history(subject_id: str, *, repo_root: Path | None = None) -> LifecycleHistory:
    repo_root = repo_root or Path.cwd()
    path = repo_root / LIFECYCLE_DIR / f"{subject_id}.json"
    if not path.is_file():
        return LifecycleHistory(subject_id=subject_id, transitions=[])
    raw = json.loads(path.read_text(encoding="utf-8"))
    return LifecycleHistory(
        subject_id=raw["subject_id"],
        transitions=[LifecycleTransition(**t) for t in raw["transitions"]],
    )


def record_transition(
    subject_id: str,
    to_state: str,
    *,
    evidence_ref: str,
    gate_summary: str,
    repo_root: Path | None = None,
) -> LifecycleHistory:
    """Append-only: loads the existing history (if any), validates the
    new state, appends ONE new transition, and rewrites the file - never
    truncates or edits a prior transition."""
    if to_state in _FORBIDDEN_STATES:
        raise LifecycleError(
            f"'{to_state}' is not a state this project's lifecycle vocabulary allows "
            f"(forbidden: {sorted(_FORBIDDEN_STATES)}). "
            "No automatic promotion to production exists."
        )
    if to_state not in _ALLOWED_STATES:
        raise LifecycleError(
            f"Unknown lifecycle state '{to_state}'. Allowed: {sorted(_ALLOWED_STATES)}."
        )

    repo_root = repo_root or Path.cwd()
    history = load_lifecycle_history(subject_id, repo_root=repo_root)
    transition = LifecycleTransition(
        from_state=history.current_state,
        to_state=to_state,
        evidence_ref=evidence_ref,
        gate_summary=gate_summary,
        triggered_by="manual_validation_run",
    )
    updated = LifecycleHistory(
        subject_id=subject_id, transitions=[*history.transitions, transition]
    )

    out_dir = repo_root / LIFECYCLE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{subject_id}.json").write_text(
        json.dumps(updated.to_dict(), indent=2), encoding="utf-8"
    )
    return updated
