"""The 14 independent validation gates and the final decision (Phase 9
section 19). Each gate carries its own `severity` - most correctness/
reproducibility gates are `blocking` (any failure forces
`validation_failed`); a few diagnostic gates (coefficient stability,
subgroup gaps, robustness magnitude) are `non_blocking` - a concerning
finding there becomes a documented LIMITATION
(`validation_passed_with_limitations`), never an automatic rejection,
matching this project's "not a compliance assessment" posture.

The only three allowed outcomes are `validation_passed`,
`validation_passed_with_limitations`, `validation_failed` - never forced,
and "no model eligible" is treated the same way Phase 8 treated it: a
legitimate result, not something this module tries to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Severity = Literal["blocking", "non_blocking"]
GateStatus = Literal["pass", "fail", "warning"]
Decision = Literal["validation_passed", "validation_passed_with_limitations", "validation_failed"]


@dataclass(frozen=True)
class ValidationGate:
    name: str
    status: GateStatus
    severity: Severity
    evidence: str
    threshold: str
    result: str
    justification: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "severity": self.severity,
            "evidence": self.evidence,
            "threshold": self.threshold,
            "result": self.result,
            "justification": self.justification,
        }


@dataclass(frozen=True)
class ValidationDecision:
    experiment_id: str
    gates: list[ValidationGate]
    decision: Decision
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "gates": [g.to_dict() for g in self.gates],
            "decision": self.decision,
            "reason": self.reason,
        }


def build_gate(
    name: str,
    passed: bool,
    *,
    severity: Severity,
    evidence: str,
    threshold: str,
    warn_instead_of_fail: bool = False,
) -> ValidationGate:
    if passed:
        status: GateStatus = "pass"
        result = "OK"
    elif warn_instead_of_fail:
        status = "warning"
        result = "LIMITATION"
    else:
        status = "fail"
        result = "FAIL"
    return ValidationGate(
        name=name,
        status=status,
        severity=severity,
        evidence=evidence,
        threshold=threshold,
        result=result,
        justification=evidence,
    )


def make_decision(experiment_id: str, gates: list[ValidationGate]) -> ValidationDecision:
    blocking_failures = [g for g in gates if g.severity == "blocking" and g.status == "fail"]
    limitations = [
        g for g in gates if g.status in ("fail", "warning") and g.severity == "non_blocking"
    ]

    if blocking_failures:
        names = ", ".join(g.name for g in blocking_failures)
        return ValidationDecision(
            experiment_id=experiment_id,
            gates=gates,
            decision="validation_failed",
            reason=f"Blocking gate(s) failed: {names}.",
        )
    if limitations:
        names = ", ".join(g.name for g in limitations)
        return ValidationDecision(
            experiment_id=experiment_id,
            gates=gates,
            decision="validation_passed_with_limitations",
            reason=f"All blocking gates passed; non-blocking gate(s) raised limitations: {names}.",
        )
    return ValidationDecision(
        experiment_id=experiment_id,
        gates=gates,
        decision="validation_passed",
        reason="All 14 gates passed with no limitations flagged.",
    )


def write_decision(decision: ValidationDecision, *, repo_root: Path | None = None) -> Path:
    import json

    repo_root = repo_root or Path.cwd()
    out_dir = repo_root / "reports" / "model_validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "decision.json"
    path.write_text(json.dumps(decision.to_dict(), indent=2), encoding="utf-8")
    return path
