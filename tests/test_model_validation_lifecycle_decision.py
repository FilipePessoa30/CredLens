"""Tests for credlens.model_validation.lifecycle/decision (Phase 9
sections 18, 19) - fast, pure-function/file-IO tests using `tmp_path`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from credlens.model_validation.decision import build_gate, make_decision, write_decision
from credlens.model_validation.lifecycle import (
    LifecycleError,
    load_lifecycle_history,
    record_transition,
)


class TestLifecycle:
    def test_first_transition_starts_from_experiment(self, tmp_path: Path) -> None:
        history = record_transition(
            "MODEL_x", "candidate", evidence_ref="ref1", gate_summary="ok", repo_root=tmp_path
        )
        assert history.transitions[0].from_state == "experiment"
        assert history.current_state == "candidate"

    def test_transitions_are_append_only(self, tmp_path: Path) -> None:
        record_transition(
            "MODEL_y", "candidate", evidence_ref="r1", gate_summary="ok", repo_root=tmp_path
        )
        history = record_transition(
            "MODEL_y", "validation_passed", evidence_ref="r2", gate_summary="ok", repo_root=tmp_path
        )
        assert len(history.transitions) == 2
        assert history.transitions[0].to_state == "candidate"
        assert history.transitions[1].to_state == "validation_passed"

    def test_production_state_is_forbidden(self, tmp_path: Path) -> None:
        with pytest.raises(LifecycleError):
            record_transition(
                "MODEL_z", "production", evidence_ref="r", gate_summary="x", repo_root=tmp_path
            )

    def test_deployed_state_is_forbidden(self, tmp_path: Path) -> None:
        with pytest.raises(LifecycleError):
            record_transition(
                "MODEL_z", "deployed", evidence_ref="r", gate_summary="x", repo_root=tmp_path
            )

    def test_unknown_state_raises(self, tmp_path: Path) -> None:
        with pytest.raises(LifecycleError):
            record_transition(
                "MODEL_z",
                "not_a_real_state",
                evidence_ref="r",
                gate_summary="x",
                repo_root=tmp_path,
            )

    def test_loading_history_for_unknown_subject_starts_at_experiment(self, tmp_path: Path) -> None:
        history = load_lifecycle_history("MODEL_never_seen", repo_root=tmp_path)
        assert history.current_state == "experiment"
        assert history.transitions == []


class TestDecision:
    def test_blocking_failure_forces_validation_failed(self) -> None:
        gates = [
            build_gate("g1", True, severity="blocking", evidence="e", threshold="t"),
            build_gate("g2", False, severity="blocking", evidence="e", threshold="t"),
        ]
        decision = make_decision("EXP_x", gates)
        assert decision.decision == "validation_failed"

    def test_non_blocking_warning_yields_passed_with_limitations(self) -> None:
        gates = [
            build_gate("g1", True, severity="blocking", evidence="e", threshold="t"),
            build_gate(
                "g2",
                False,
                severity="non_blocking",
                evidence="e",
                threshold="t",
                warn_instead_of_fail=True,
            ),
        ]
        decision = make_decision("EXP_x", gates)
        assert decision.decision == "validation_passed_with_limitations"
        assert gates[1].status == "warning"

    def test_all_pass_yields_validation_passed(self) -> None:
        gates = [build_gate("g1", True, severity="blocking", evidence="e", threshold="t")]
        decision = make_decision("EXP_x", gates)
        assert decision.decision == "validation_passed"

    def test_write_decision_creates_file(self, tmp_path: Path) -> None:
        gates = [build_gate("g1", True, severity="blocking", evidence="e", threshold="t")]
        decision = make_decision("EXP_x", gates)
        path = write_decision(decision, repo_root=tmp_path)
        assert path.is_file()
        assert "validation_passed" in path.read_text(encoding="utf-8")
