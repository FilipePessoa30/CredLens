"""Tests for the `credlens synthetic ...` CLI commands.

Run against this repository's real config/synthetic/scenarios/ blueprints
and contracts/ - offline and read-only by design. `credlens synthetic
generate` is required to NOT generate anything: it must print a fixed
"not implemented" message and exit 1 (see docs/roadmap.md and Phase 3
scope - generation itself is a future phase).
"""

from __future__ import annotations

import pytest

from credlens.cli import main


def test_synthetic_scenarios_lists_all_six(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["synthetic", "scenarios"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "baseline" in captured.out
    assert "policy_expansion" in captured.out
    assert "policy_tightening" in captured.out
    assert "macroeconomic_stress" in captured.out
    assert "collections_change" in captured.out
    assert "data_quality_incident" in captured.out
    assert "requires_calibration" in captured.out


def test_synthetic_plan_reports_readiness_without_fabricating_completion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["synthetic", "plan"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Scenario blueprints defined:                 6" in captured.out
    assert "Blueprints still requiring calibration:      6/6" in captured.out
    assert "Not implemented: scheduled for the synthetic" in captured.out


def test_synthetic_validate_blueprints_all_pass(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["synthetic", "validate-blueprints"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Result: OK" in captured.out
    assert "[FAIL]" not in captured.out
    for scenario_id in (
        "baseline",
        "policy_expansion",
        "policy_tightening",
        "macroeconomic_stress",
        "collections_change",
        "data_quality_incident",
    ):
        assert scenario_id in captured.out


def test_synthetic_generate_is_not_implemented_and_exits_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The exact required behavior: no generation, a clear fixed message,
    and a failing exit code (never silently succeeding)."""
    exit_code = main(["synthetic", "generate"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out.strip() == "Not implemented: scheduled for the synthetic generation phase."


def test_synthetic_no_subcommand_prints_usage_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["synthetic"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "usage: credlens synthetic" in captured.out


def test_synthetic_generate_never_writes_to_data_directory() -> None:
    """No side effect: running `generate` must not create any file
    anywhere - it is purely a fixed-message command in this phase."""
    import os

    before = set(os.listdir("."))
    main(["synthetic", "generate"])
    after = set(os.listdir("."))

    assert before == after
