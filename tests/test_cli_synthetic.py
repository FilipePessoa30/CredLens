"""Tests for the `credlens synthetic ...` CLI commands.

`generate` is real as of Phase 4A (baseline scenario only) - these tests
run it for real, at `smoke` scale (a couple hundred customers, well
under a second), against this repository's real config/contracts, and
clean up whatever they write under data/synthetic(_truth)/ afterward so
the repository is left exactly as they found it. No network is used
anywhere in this file.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.cli import main
from credlens.generation.config import load_generation_config

# A seed unlikely to collide with any seed a human/report run would pick.
_TEST_SEED = 918_273_645


def _run_dirs_for(seed: int) -> tuple[Path, Path]:
    config = load_generation_config()
    from credlens.generation.manifest import canonical_config_hash
    from credlens.generation.orchestrator import _compute_generation_run_id

    config_hash = canonical_config_hash(config)
    run_id = _compute_generation_run_id("baseline", "smoke", seed, config_hash)
    return (
        Path(config.output.operational_dir) / run_id,
        Path(config.output.truth_dir) / run_id,
    )


@pytest.fixture
def cleanup_generated_run() -> Iterator[list[Path]]:
    """Removes this test file's generated run directories after each
    test, regardless of outcome, so the repository's real data/synthetic/
    stays exactly as it was before the test suite ran."""
    created: list[Path] = []
    yield created
    for path in created:
        if path.exists():
            shutil.rmtree(path)


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


def test_synthetic_plan_reports_readiness(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["synthetic", "plan"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Scenario blueprints defined:                 6" in captured.out
    assert "generate" in captured.out


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


def test_synthetic_no_subcommand_prints_usage_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["synthetic"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "usage: credlens synthetic" in captured.out


class TestSyntheticGenerate:
    def test_non_calibrated_scenario_is_rejected(self, capsys: pytest.CaptureFixture[str]) -> None:
        # data_quality_incident has no generation.yaml as of Phase 4B -
        # it remains requires_calibration, unlike policy_expansion/
        # policy_tightening/macroeconomic_stress/collections_change/
        # contract_coverage, which all became executable this phase.
        exit_code = main(
            [
                "synthetic",
                "generate",
                "--scenario",
                "data_quality_incident",
                "--scale",
                "smoke",
                "--seed",
                "1",
            ]
        )
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "requires_calibration" in captured.out

    def test_baseline_smoke_generation_succeeds(
        self, capsys: pytest.CaptureFixture[str], cleanup_generated_run: list[Path]
    ) -> None:
        operational_dir, truth_dir = _run_dirs_for(_TEST_SEED)
        cleanup_generated_run.extend([operational_dir, truth_dir])

        exit_code = main(
            [
                "synthetic",
                "generate",
                "--scenario",
                "baseline",
                "--scale",
                "smoke",
                "--seed",
                str(_TEST_SEED),
                "--force",
            ]
        )
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "status:            completed" in captured.out
        assert "contracts passed:  True" in captured.out
        assert (operational_dir / "operational" / "customers.parquet").is_file()
        assert (operational_dir / "manifest.json").is_file()
        assert (truth_dir / "latent_customer_truth.parquet").is_file()

    def test_generate_without_force_refuses_to_overwrite(
        self, capsys: pytest.CaptureFixture[str], cleanup_generated_run: list[Path]
    ) -> None:
        operational_dir, truth_dir = _run_dirs_for(_TEST_SEED)
        cleanup_generated_run.extend([operational_dir, truth_dir])

        args = [
            "synthetic",
            "generate",
            "--scenario",
            "baseline",
            "--scale",
            "smoke",
            "--seed",
            str(_TEST_SEED),
        ]
        first = main([*args, "--force"])
        assert first == 0

        second = main(args)  # no --force this time
        captured = capsys.readouterr()

        assert second == 1
        assert "already exists" in captured.out
        assert "--force" in captured.out

    def test_generate_never_writes_outside_configured_output_dirs(
        self, cleanup_generated_run: list[Path]
    ) -> None:
        operational_dir, truth_dir = _run_dirs_for(_TEST_SEED)
        cleanup_generated_run.extend([operational_dir, truth_dir])

        before = set(Path(".").iterdir())
        main(
            [
                "synthetic",
                "generate",
                "--scenario",
                "baseline",
                "--scale",
                "smoke",
                "--seed",
                str(_TEST_SEED),
                "--force",
            ]
        )
        after = set(Path(".").iterdir())

        # data/ and reports/ may pre-exist; the only NEW top-level entries
        # allowed are things already present before (generation writes
        # inside data/synthetic(_truth)/, never creates new repo-root
        # entries).
        assert after == before


class TestSyntheticValidateInspectManifest:
    @pytest.fixture(autouse=True)
    def _generated_run(self, cleanup_generated_run: list[Path]) -> None:
        operational_dir, truth_dir = _run_dirs_for(_TEST_SEED)
        cleanup_generated_run.extend([operational_dir, truth_dir])
        exit_code = main(
            [
                "synthetic",
                "generate",
                "--scenario",
                "baseline",
                "--scale",
                "smoke",
                "--seed",
                str(_TEST_SEED),
                "--force",
            ]
        )
        assert exit_code == 0
        self.run_id = operational_dir.name

    def test_validate_run_passes_strict(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["synthetic", "validate", "--run-id", self.run_id])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Result: OK" in captured.out

    def test_validate_run_unknown_id_fails_cleanly(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["synthetic", "validate", "--run-id", "RUN_does_not_exist"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "Error:" in captured.out

    def test_validate_run_path_traversal_is_rejected(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["synthetic", "validate", "--run-id", "../../../../etc"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "Error:" in captured.out

    def test_inspect_reports_table_row_counts(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["synthetic", "inspect", "--run-id", self.run_id])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "customers" in captured.out
        assert "rows" in captured.out
        assert "status:                     completed" in captured.out

    def test_inspect_unknown_run_id_fails_cleanly(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["synthetic", "inspect", "--run-id", "RUN_does_not_exist"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "Error:" in captured.out

    def test_manifest_prints_valid_json_with_required_fields(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import json

        exit_code = main(["synthetic", "manifest", "--run-id", self.run_id])
        captured = capsys.readouterr()

        assert exit_code == 0
        manifest = json.loads(captured.out)
        assert manifest["generation_run_id"] == self.run_id
        assert manifest["seed"] == _TEST_SEED
        assert manifest["scenario"] == "baseline"
        assert manifest["scale"] == "smoke"
        assert "global_content_hash" in manifest
        assert "tables" in manifest
        assert manifest["validation_passed"] is True

    def test_manifest_unknown_run_id_fails_cleanly(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["synthetic", "manifest", "--run-id", "RUN_does_not_exist"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "Error:" in captured.out
