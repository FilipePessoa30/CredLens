"""Phase 10 gate B - guards against tolerance-masking patterns creeping
back into `.github/workflows/ci.yml`. A `|| true` (or equivalent) after a
critical validation command silently turns a real failure into a green
check mark; the incident this test defends against is exactly that
pattern, previously present on the CI-scoped independent-validation step
(removed once the permutation counts were raised enough - see gate B's
note in that step and in `config/model_validation/validation.yml`) - to
mask an unwinnable-at-that-scale statistical gate.

Fast, pure parsing test - no subprocess, no CredLens import.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from credlens.release.integrity import CI_WORKFLOW_MASKING_PATTERNS

WORKFLOW_PATH = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"

# Shared with credlens.release.integrity (the `credlens release validate`
# CLI check runs the exact same denylist/parser against this same file) -
# a denylist of KNOWN masking idioms, not an attempt at a general shell
# parser; anything added here must be something actually seen (or
# plausibly used) to hide a failure.
_TOLERANCE_MASKING_PATTERNS = CI_WORKFLOW_MASKING_PATTERNS

# Commands that represent a critical validation/gate check - if any of
# these substrings appear in a step's `run:` text, that step is treated
# as security-critical and is held to the no-masking rule even more
# strictly (this list is informational for the assertion messages; the
# denylist scan above already applies to every step regardless).
_CRITICAL_VALIDATION_COMMANDS = (
    "validate-independent",
    "audit-negative-controls",
    "audit-collinearity",
    "model validate",
    "dbt build",
    "dbt test",
    "pytest",
    "ruff check",
    "mypy",
)


def _load_workflow() -> tuple[dict[str, Any], str]:
    assert WORKFLOW_PATH.is_file(), f"CI workflow not found at {WORKFLOW_PATH}"
    with WORKFLOW_PATH.open(encoding="utf-8") as handle:
        raw_text = handle.read()
    # PyYAML chokes on the bare `on:` workflow-trigger key only when it is
    # parsed as a boolean by very old YAML 1.1 loaders; the modern
    # safe_load handles it correctly, so no special-casing is needed here.
    workflow: dict[str, Any] = yaml.safe_load(raw_text)
    return workflow, raw_text


def _iter_steps(workflow: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Yields (job_name, step_name, step_dict) for every step with a `run:` key."""
    steps: list[tuple[str, str, dict[str, Any]]] = []
    for job_name, job in workflow.get("jobs", {}).items():
        for step in job.get("steps", []):
            if "run" in step:
                steps.append((job_name, step.get("name", "<unnamed>"), step))
    return steps


class TestNoToleranceMasking:
    def test_workflow_file_exists_and_parses(self) -> None:
        workflow, _ = _load_workflow()
        assert "jobs" in workflow
        assert len(workflow["jobs"]) > 0

    def test_no_masking_pattern_in_any_run_step(self) -> None:
        workflow, _ = _load_workflow()
        offenders = []
        for job_name, step_name, step in _iter_steps(workflow):
            run_text = step["run"]
            for pattern in _TOLERANCE_MASKING_PATTERNS:
                if pattern in run_text:
                    offenders.append(f"job={job_name!r} step={step_name!r} pattern={pattern!r}")
        assert offenders == [], (
            f"Found tolerance-masking pattern(s) hiding a possible critical failure: {offenders}"
        )

    def test_no_continue_on_error_true_anywhere(self) -> None:
        workflow, _ = _load_workflow()
        offenders = []
        for job_name, job in workflow.get("jobs", {}).items():
            if job.get("continue-on-error") is True:
                offenders.append(f"job={job_name!r} (job-level)")
            for step in job.get("steps", []):
                if step.get("continue-on-error") is True:
                    offenders.append(f"job={job_name!r} step={step.get('name', '<unnamed>')!r}")
        assert offenders == [], f"Found continue-on-error: true: {offenders}"

    @pytest.mark.parametrize("command_substring", _CRITICAL_VALIDATION_COMMANDS)
    def test_critical_commands_when_present_are_never_followed_by_masking(
        self, command_substring: str
    ) -> None:
        workflow, _ = _load_workflow()
        found_at_least_one = False
        for job_name, step_name, step in _iter_steps(workflow):
            run_text = step["run"]
            if command_substring not in run_text:
                continue
            found_at_least_one = True
            for pattern in _TOLERANCE_MASKING_PATTERNS:
                assert pattern not in run_text, (
                    f"Critical command '{command_substring}' in job={job_name!r} "
                    f"step={step_name!r} is masked by pattern {pattern!r}"
                )
        # Not every command is guaranteed to be present (ruff/mypy/pytest
        # etc. run in different jobs than dbt/model validation) - this
        # loop is a no-op scan when a given command isn't used at all,
        # which is fine; the point is that IF it is used, it is unmasked.
        _ = found_at_least_one

    def test_model_validation_ci_scoped_step_has_no_trailing_true(self) -> None:
        _, raw_text = _load_workflow()
        assert "validate-independent --model-id CI_MODEL_SMOKE_v1 --ci" in raw_text
        assert "validate-independent --model-id CI_MODEL_SMOKE_v1 --ci || true" not in raw_text

    def test_negative_controls_ci_scoped_permutation_counts_can_mathematically_pass(self) -> None:
        """At CI's reduced permutation count, alpha must be reachable -
        i.e. 1/(n_ci+1) <= alpha - otherwise the gate is unwinnable and a
        future author would be tempted to reintroduce `|| true`."""
        validation_cfg_path = (
            Path(__file__).resolve().parent.parent
            / "config"
            / "model_validation"
            / "validation.yml"
        )
        cfg = yaml.safe_load(validation_cfg_path.read_text(encoding="utf-8"))
        perm_cfg = cfg["permutation_test"]
        for control_name in ("control1_score_label", "control2_pipeline_retrain"):
            control_cfg = perm_cfg[control_name]
            n_ci = int(control_cfg["n_permutations_ci"])
            alpha = float(control_cfg["alpha"])
            smallest_achievable_p = 1.0 / (n_ci + 1)
            assert smallest_achievable_p <= alpha, (
                f"{control_name}: with n_permutations_ci={n_ci}, the smallest "
                f"achievable empirical p-value is {smallest_achievable_p:.4f}, which "
                f"can never satisfy alpha={alpha} - this gate would be mathematically "
                "unwinnable at CI scale, inviting a `|| true` workaround."
            )
