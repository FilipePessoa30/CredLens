"""CLI smoke tests for the Phase 4B synthetic commands: generate-suite,
compare, validate-suite, monte-carlo, profile, and `generate --scenario
contract_coverage`. All at 'smoke' scale, no network - see
tests/test_cli_synthetic.py for the Phase 4A command tests this extends.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.cli import main
from credlens.generation.config import (
    CRN_SCENARIOS,
    config_path_for_scenario,
    load_generation_config,
)

_SEED = 555_444_333


@pytest.fixture
def cleanup_4b_runs() -> Iterator[None]:
    yield
    config = load_generation_config()
    for base in (config.output.operational_dir, config.output.truth_dir):
        base_path = Path(base)
        if not base_path.is_dir():
            continue
        for run_dir in base_path.iterdir():
            if str(_SEED) in run_dir.name:
                shutil.rmtree(run_dir)
    manifest_path = Path("reports/synthetic_validation/suites") / f"SUITE_smoke_{_SEED}.json"
    if manifest_path.is_file():
        manifest_path.unlink()
    mc_report = Path("reports/synthetic_validation/monte_carlo_summary.json")
    if mc_report.is_file():
        mc_report.unlink()


def test_generate_contract_coverage(
    capsys: pytest.CaptureFixture[str], cleanup_4b_runs: None
) -> None:
    exit_code = main(
        [
            "synthetic",
            "generate",
            "--scenario",
            "contract_coverage",
            "--scale",
            "smoke",
            "--seed",
            str(_SEED),
            "--force",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "status:            completed" in captured.out


def test_generate_suite_then_validate_suite(
    capsys: pytest.CaptureFixture[str], cleanup_4b_runs: None
) -> None:
    exit_code = main(
        ["synthetic", "generate-suite", "--scale", "smoke", "--seed", str(_SEED), "--force"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert f"SUITE_smoke_{_SEED}" in captured.out
    for scenario in CRN_SCENARIOS:
        assert scenario in captured.out

    exit_code = main(["synthetic", "validate-suite", "--suite-id", f"SUITE_smoke_{_SEED}"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Result: OK" in captured.out


def test_validate_suite_unknown_suite_fails(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["synthetic", "validate-suite", "--suite-id", "SUITE_does_not_exist"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Error" in captured.out


def test_compare_two_runs(capsys: pytest.CaptureFixture[str], cleanup_4b_runs: None) -> None:
    main(["synthetic", "generate-suite", "--scale", "smoke", "--seed", str(_SEED), "--force"])
    capsys.readouterr()

    from credlens.generation.config import config_path_for_scenario
    from credlens.generation.config import load_generation_config as lgc
    from credlens.generation.manifest import canonical_config_hash
    from credlens.generation.orchestrator import _compute_generation_run_id

    baseline_hash = canonical_config_hash(lgc())
    baseline_run_id = _compute_generation_run_id("baseline", "smoke", _SEED, baseline_hash)
    expansion_hash = canonical_config_hash(lgc(config_path_for_scenario("policy_expansion")))
    expansion_run_id = _compute_generation_run_id(
        "policy_expansion", "smoke", _SEED, expansion_hash
    )

    exit_code = main(
        ["synthetic", "compare", "--baseline", baseline_run_id, "--candidate", expansion_run_id]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "approval_rate" in captured.out


def test_monte_carlo_two_seeds(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "synthetic",
            "monte-carlo",
            "--scenario",
            "policy_tightening",
            "--scale",
            "smoke",
            "--seeds",
            "2",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "approval_rate" in captured.out

    # Delete ONLY the exact runs this test's own monte-carlo call created
    # (baseline + policy_tightening, seeds 2026/2027) - NOT a substring
    # match on "2026"/"2027" in the directory name, which would also
    # delete any unrelated run that happens to share one of those seeds
    # (e.g. a demonstration run some other scenario made with seed 2026).
    # A prior version of this fixture did exactly that and silently swept
    # up other, unrelated run directories - see docs/adr/0010's Phase 5
    # report for how this was found.
    from credlens.generation.manifest import canonical_config_hash
    from credlens.generation.orchestrator import _compute_generation_run_id

    baseline_hash = canonical_config_hash(load_generation_config())
    tightening_hash = canonical_config_hash(
        load_generation_config(config_path_for_scenario("policy_tightening"))
    )
    scenario_hashes = (("baseline", baseline_hash), ("policy_tightening", tightening_hash))
    run_ids = [
        _compute_generation_run_id(scenario, "smoke", seed, config_hash)
        for seed in (2026, 2027)
        for scenario, config_hash in scenario_hashes
    ]

    config = load_generation_config()
    for base in (config.output.operational_dir, config.output.truth_dir):
        base_path = Path(base)
        for run_id in run_ids:
            run_dir = base_path / run_id
            if run_dir.exists():
                shutil.rmtree(run_dir, ignore_errors=True)
    mc_report = Path("reports/synthetic_validation/monte_carlo_summary.json")
    if mc_report.is_file():
        mc_report.unlink()


def test_profile_baseline(capsys: pytest.CaptureFixture[str], cleanup_4b_runs: None) -> None:
    exit_code = main(["synthetic", "profile", "--scale", "smoke", "--seed", str(_SEED)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "duration_seconds" in captured.out
    assert "global_content_hash" in captured.out
