"""Tests for Phase 10B (Release Candidate Acceptance Remediation)'s new
release-engineering modules: `credlens.release.source_snapshot`
(content-based fingerprint, not just `git rev-parse HEAD`),
`credlens.release.coverage_gate` (persisted, staleness-checked coverage
acceptance gate), `credlens.release.monitoring_gate` (persisted,
staleness-checked detection/false-alert acceptance gate), and
`credlens.release.errata` (append-only readiness-decision corrections).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import ClassVar

import pytest


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=root, check=True)


@pytest.fixture
def tiny_git_repo(tmp_path: Path) -> Path:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("world", encoding="utf-8")
    _init_git_repo(tmp_path)
    return tmp_path


class TestSourceSnapshot:
    def test_fingerprint_is_deterministic_for_unchanged_tree(self, tiny_git_repo: Path) -> None:
        from credlens.release.source_snapshot import compute_source_snapshot

        first = compute_source_snapshot(tiny_git_repo)
        second = compute_source_snapshot(tiny_git_repo)
        assert first.fingerprint == second.fingerprint
        assert first.n_files == 2
        assert first.working_tree_clean is True

    def test_fingerprint_changes_when_tracked_file_content_changes(
        self, tiny_git_repo: Path
    ) -> None:
        from credlens.release.source_snapshot import compute_source_snapshot

        before = compute_source_snapshot(tiny_git_repo)
        (tiny_git_repo / "a.txt").write_text("hello, changed", encoding="utf-8")
        after = compute_source_snapshot(tiny_git_repo)
        assert before.fingerprint != after.fingerprint
        # working tree is now dirty (uncommitted change) but base_commit
        # (git rev-parse HEAD) is UNCHANGED - exactly the gap a
        # HEAD-only fingerprint would miss.
        assert before.base_commit == after.base_commit
        assert after.working_tree_clean is False

    def test_fingerprint_is_blind_to_a_new_untracked_file(self, tiny_git_repo: Path) -> None:
        """An untracked file (never `git add`ed) is invisible to `git
        ls-files` by design - this fingerprint covers TRACKED source, not
        arbitrary scratch files left in the working directory."""
        from credlens.release.source_snapshot import compute_source_snapshot

        before = compute_source_snapshot(tiny_git_repo)
        (tiny_git_repo / "scratch.tmp").write_text("not tracked", encoding="utf-8")
        after = compute_source_snapshot(tiny_git_repo)
        assert before.fingerprint == after.fingerprint

    def test_a_tracked_but_deleted_file_does_not_crash_the_fingerprint(
        self, tiny_git_repo: Path
    ) -> None:
        """`rm` without `git rm` leaves a file in git's index but gone
        from the working tree - a real, legitimate uncommitted change
        (git status would show it as deleted), not an I/O error this
        function should raise on."""
        from credlens.release.source_snapshot import compute_source_snapshot

        before = compute_source_snapshot(tiny_git_repo)
        (tiny_git_repo / "a.txt").unlink()
        after = compute_source_snapshot(tiny_git_repo)
        assert after.fingerprint != before.fingerprint
        assert after.n_files == before.n_files - 1

    def test_evidence_files_writing_each_other_does_not_create_a_fingerprint_cycle(
        self, tmp_path: Path
    ) -> None:
        """Real, empirically-found bug (Phase 10B): coverage_snapshot.
        json/detection_evaluation.json/false_alert_study.json each stamp
        themselves with a fingerprint of 'every tracked file' - if all
        three are themselves tracked, writing one invalidates the
        others' stamped fingerprint, and no sequence of re-runs can ever
        converge. Excluding these three specific evidence files from the
        digest breaks the cycle: writing them must NEVER change the
        fingerprint."""
        (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
        reports_dir = tmp_path / "reports" / "release"
        reports_dir.mkdir(parents=True)
        (reports_dir / "coverage_snapshot.json").write_text('{"coverage_percent": 90}')
        (reports_dir / "release_manifest.json").write_text('{"readiness_decision": "x"}')
        (reports_dir / "sbom.cyclonedx.json").write_text('{"serialNumber": "urn:uuid:aaa"}')
        monitoring_dir = tmp_path / "reports" / "monitoring"
        monitoring_dir.mkdir(parents=True)
        (monitoring_dir / "detection_evaluation.json").write_text('{"rate": 0.5}')
        (monitoring_dir / "false_alert_study.json").write_text('{"rate": 0.1}')
        _init_git_repo(tmp_path)

        from credlens.release.source_snapshot import compute_source_snapshot

        before = compute_source_snapshot(tmp_path)
        (reports_dir / "coverage_snapshot.json").write_text('{"coverage_percent": 99}')
        (reports_dir / "release_manifest.json").write_text('{"readiness_decision": "y"}')
        (reports_dir / "sbom.cyclonedx.json").write_text('{"serialNumber": "urn:uuid:bbb"}')
        (monitoring_dir / "detection_evaluation.json").write_text('{"rate": 1.0}')
        (monitoring_dir / "false_alert_study.json").write_text('{"rate": 0.03}')
        after = compute_source_snapshot(tmp_path)
        assert before.fingerprint == after.fingerprint

    def test_excludes_cache_and_coverage_paths_even_if_tracked(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "x.pyc").write_bytes(b"\x00\x01")
        (tmp_path / "coverage.json").write_text('{"totals": {}}', encoding="utf-8")
        _init_git_repo(tmp_path)

        from credlens.release.source_snapshot import compute_source_snapshot

        snapshot = compute_source_snapshot(tmp_path)
        assert snapshot.n_files == 1

    def test_to_dict_shape(self, tiny_git_repo: Path) -> None:
        from credlens.release.source_snapshot import compute_source_snapshot

        snapshot = compute_source_snapshot(tiny_git_repo)
        payload = snapshot.to_dict()
        assert payload == {
            "fingerprint": snapshot.fingerprint,
            "n_files": snapshot.n_files,
            "base_commit": snapshot.base_commit,
            "working_tree_clean": snapshot.working_tree_clean,
        }

    @pytest.mark.slow
    def test_real_repo_produces_a_stable_fingerprint(self) -> None:
        from credlens.release.source_snapshot import compute_source_snapshot

        first = compute_source_snapshot(Path.cwd())
        second = compute_source_snapshot(Path.cwd())
        assert first.fingerprint == second.fingerprint
        assert first.n_files > 100


_REAL_COMMAND = (
    "uv run pytest --cov=credlens --cov-report=json:coverage.json --cov-fail-under=95 -q"
)


class TestCoverageGate:
    def _write_fake_coverage_json(
        self,
        root: Path,
        *,
        percent: float,
        num_statements: int = 1000,
        missing_lines: int | None = None,
    ) -> Path:
        covered = int(percent * num_statements / 100)
        totals: dict[str, object] = {
            "percent_covered": percent,
            "num_statements": num_statements,
            "covered_lines": covered,
        }
        totals["missing_lines"] = (
            missing_lines if missing_lines is not None else num_statements - covered
        )
        path = root / "coverage.json"
        path.write_text(json.dumps({"totals": totals}), encoding="utf-8")
        return path

    def _build_and_write(
        self,
        coverage_json: Path,
        *,
        test_count: int,
        repo_root: Path,
        command: str = _REAL_COMMAND,
        pytest_exit_code: int = 0,
    ) -> None:
        from credlens.release.coverage_gate import build_coverage_snapshot, write_coverage_snapshot

        snapshot = build_coverage_snapshot(
            coverage_json,
            test_count=test_count,
            command=command,
            pytest_exit_code=pytest_exit_code,
            repo_root=repo_root,
        )
        write_coverage_snapshot(snapshot, repo_root=repo_root)

    def test_missing_snapshot_fails(self, tiny_git_repo: Path) -> None:
        from credlens.release.coverage_gate import check_coverage_gate

        result = check_coverage_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "No coverage snapshot" in result.detail

    def test_schema_incompatible_snapshot_degrades_to_missing_not_a_crash(
        self, tiny_git_repo: Path
    ) -> None:
        """A snapshot written by an OLDER version of this module (before
        missing_statements/command/pytest_exit_code/project_version
        existed) must fail the gate gracefully as 'no valid snapshot',
        never crash `check_coverage_gate`/`load_coverage_snapshot` with
        an unhandled TypeError - the exact real gap found when Fase 10C
        added these fields on top of the Phase 10B official evidence
        file still on disk in its old shape."""
        from credlens.release.coverage_gate import SNAPSHOT_PATH, check_coverage_gate

        old_schema_snapshot = {
            "coverage_percent": 96.0,
            "total_statements": 1000,
            "covered_statements": 960,
            "test_count": 1500,
            "source_snapshot_fingerprint": "deadbeef",
            "measured_at_utc": "2026-01-01T00:00:00+00:00",
        }
        path = tiny_git_repo / SNAPSHOT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(old_schema_snapshot), encoding="utf-8")

        result = check_coverage_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "No coverage snapshot" in result.detail

    def test_build_snapshot_requires_a_real_coverage_json(self, tiny_git_repo: Path) -> None:
        from credlens.release.coverage_gate import CoverageGateError, build_coverage_snapshot

        with pytest.raises(CoverageGateError):
            build_coverage_snapshot(
                tiny_git_repo / "nope.json",
                test_count=10,
                command=_REAL_COMMAND,
                pytest_exit_code=0,
            )

    def test_build_snapshot_rejects_invalid_json(self, tiny_git_repo: Path) -> None:
        from credlens.release.coverage_gate import CoverageGateError, build_coverage_snapshot

        bad = tiny_git_repo / "coverage.json"
        bad.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(CoverageGateError):
            build_coverage_snapshot(
                bad,
                test_count=10,
                command=_REAL_COMMAND,
                pytest_exit_code=0,
                repo_root=tiny_git_repo,
            )

    def test_build_snapshot_rejects_missing_totals_section(self, tiny_git_repo: Path) -> None:
        from credlens.release.coverage_gate import CoverageGateError, build_coverage_snapshot

        no_totals = tiny_git_repo / "coverage.json"
        no_totals.write_text(json.dumps({"files": {}}), encoding="utf-8")
        with pytest.raises(CoverageGateError):
            build_coverage_snapshot(
                no_totals,
                test_count=10,
                command=_REAL_COMMAND,
                pytest_exit_code=0,
                repo_root=tiny_git_repo,
            )

    def test_build_snapshot_rejects_inconsistent_statement_totals(
        self, tiny_git_repo: Path
    ) -> None:
        """Fase 10C section 10 - num_statements must equal covered_lines +
        missing_lines; a tampered/corrupted coverage.json where they
        don't add up must never be silently accepted."""
        from credlens.release.coverage_gate import CoverageGateError, build_coverage_snapshot

        bad_json = self._write_fake_coverage_json(
            tiny_git_repo, percent=99.0, num_statements=1000, missing_lines=5
        )
        # covered_lines (990) + missing_lines (5) = 995 != num_statements (1000).
        with pytest.raises(CoverageGateError, match="inconsistent"):
            build_coverage_snapshot(
                bad_json,
                test_count=10,
                command=_REAL_COMMAND,
                pytest_exit_code=0,
                repo_root=tiny_git_repo,
            )

    def test_snapshot_below_threshold_fails(self, tiny_git_repo: Path) -> None:
        from credlens.release.coverage_gate import check_coverage_gate

        coverage_json = self._write_fake_coverage_json(tiny_git_repo, percent=80.0)
        self._build_and_write(coverage_json, test_count=42, repo_root=tiny_git_repo)
        result = check_coverage_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "80.00" in result.detail

    def test_snapshot_meeting_threshold_passes(self, tiny_git_repo: Path) -> None:
        from credlens.release.coverage_gate import check_coverage_gate

        coverage_json = self._write_fake_coverage_json(tiny_git_repo, percent=97.5)
        self._build_and_write(coverage_json, test_count=1599, repo_root=tiny_git_repo)
        result = check_coverage_gate(repo_root=tiny_git_repo)
        assert result.status == "pass"

    def test_stale_snapshot_fails_even_if_coverage_was_once_high(self, tiny_git_repo: Path) -> None:
        from credlens.release.coverage_gate import check_coverage_gate

        coverage_json = self._write_fake_coverage_json(tiny_git_repo, percent=99.0)
        self._build_and_write(coverage_json, test_count=1, repo_root=tiny_git_repo)
        # Code changes AFTER the snapshot was measured.
        (tiny_git_repo / "a.txt").write_text("changed after measuring coverage", encoding="utf-8")
        result = check_coverage_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "STALE" in result.detail

    def test_divergent_fingerprint_is_the_same_as_stale(self, tiny_git_repo: Path) -> None:
        """A snapshot whose fingerprint simply doesn't match ANY current
        state (not just 'changed after') - e.g. copied in from a
        different clone/branch - must fail exactly like ordinary
        staleness."""
        from credlens.release.coverage_gate import (
            CoverageSnapshot,
            check_coverage_gate,
            write_coverage_snapshot,
        )

        fake_snapshot = CoverageSnapshot(
            coverage_percent=99.0,
            total_statements=1000,
            covered_statements=990,
            missing_statements=10,
            test_count=1500,
            command=_REAL_COMMAND,
            pytest_exit_code=0,
            project_version="9.9.9",
            source_snapshot_fingerprint="0" * 64,
            measured_at_utc="2020-01-01T00:00:00+00:00",
        )
        write_coverage_snapshot(fake_snapshot, repo_root=tiny_git_repo)
        result = check_coverage_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "STALE" in result.detail

    def test_precise_94_99_percent_fails_even_though_it_rounds_up_visually(
        self, tiny_git_repo: Path
    ) -> None:
        """Fase 10C section 18 acceptance criterion - the gate must
        reject 94.99%, the exact boundary just under the 95% floor."""
        from credlens.release.coverage_gate import check_coverage_gate

        coverage_json = self._write_fake_coverage_json(
            tiny_git_repo, percent=94.99, num_statements=10000
        )
        self._build_and_write(coverage_json, test_count=1699, repo_root=tiny_git_repo)
        result = check_coverage_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"

    def test_rounded_to_95_but_precise_value_below_still_fails(self, tiny_git_repo: Path) -> None:
        """Fase 10C section 9/18 - a value that coverage.py's own
        'percent_covered_display' would show rounded UP to "95" (e.g.
        94.996, which rounds to 95 at 0 decimal places) must still fail,
        because the gate compares the full-precision float, never the
        rounded display string."""
        from credlens.release.coverage_gate import check_coverage_gate

        coverage_json = self._write_fake_coverage_json(
            tiny_git_repo, percent=94.996, num_statements=100000
        )
        raw = json.loads(coverage_json.read_text(encoding="utf-8"))
        raw["totals"]["percent_covered_display"] = "95"
        coverage_json.write_text(json.dumps(raw), encoding="utf-8")
        self._build_and_write(coverage_json, test_count=1699, repo_root=tiny_git_repo)
        result = check_coverage_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"

    def test_nonzero_pytest_exit_code_fails_even_at_high_coverage(
        self, tiny_git_repo: Path
    ) -> None:
        """Fase 10C section 10 - a failing test (pytest exit code != 0)
        must never produce accepted coverage evidence, regardless of how
        high the resulting percentage looks."""
        from credlens.release.coverage_gate import check_coverage_gate

        coverage_json = self._write_fake_coverage_json(tiny_git_repo, percent=99.0)
        self._build_and_write(
            coverage_json, test_count=1698, repo_root=tiny_git_repo, pytest_exit_code=1
        )
        result = check_coverage_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "exited with status" in result.detail

    def test_command_missing_fail_under_flag_fails(self, tiny_git_repo: Path) -> None:
        """Fase 10C section 10 - evidence measured with a bare '--cov'
        run (no '--cov-fail-under') never enforced the threshold at
        measurement time, so it must not be accepted either."""
        from credlens.release.coverage_gate import check_coverage_gate

        coverage_json = self._write_fake_coverage_json(tiny_git_repo, percent=99.0)
        self._build_and_write(
            coverage_json,
            test_count=1699,
            repo_root=tiny_git_repo,
            command="uv run pytest --cov=credlens --cov-report=json:coverage.json",
        )
        result = check_coverage_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "--cov-fail-under" in result.detail

    def test_command_with_keyword_filter_is_an_incomplete_suite(self, tiny_git_repo: Path) -> None:
        """Fase 10C section 10 - a '-k'/'-m'-filtered run never exercised
        the FULL suite, so its coverage.json cannot stand in for a
        complete measurement."""
        from credlens.release.coverage_gate import check_coverage_gate

        coverage_json = self._write_fake_coverage_json(tiny_git_repo, percent=99.0)
        self._build_and_write(
            coverage_json,
            test_count=200,
            repo_root=tiny_git_repo,
            command=f'{_REAL_COMMAND} -k "not slow"',
        )
        result = check_coverage_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "-k/-m" in result.detail

    def test_project_version_mismatch_fails(self, tiny_git_repo: Path) -> None:
        """Fase 10C section 10/16 - evidence measured against a DIFFERENT
        declared project_version (e.g. left over from before an RC
        version bump) must not silently pass for the new version."""
        from credlens.release.coverage_gate import check_coverage_gate

        (tiny_git_repo / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "1.0.0rc1"\n', encoding="utf-8"
        )
        _init_git_repo(tiny_git_repo)
        coverage_json = self._write_fake_coverage_json(tiny_git_repo, percent=99.0)
        self._build_and_write(coverage_json, test_count=1699, repo_root=tiny_git_repo)
        # Version bumped AFTER the snapshot was measured (a real code
        # change too, so this would also be caught as stale - overwrite
        # the snapshot's fingerprint back to current to isolate the
        # version check specifically).
        from credlens.release.coverage_gate import load_coverage_snapshot, write_coverage_snapshot
        from credlens.release.source_snapshot import compute_source_snapshot

        (tiny_git_repo / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "1.0.0rc2"\n', encoding="utf-8"
        )
        stale_free_snapshot = load_coverage_snapshot(repo_root=tiny_git_repo)
        assert stale_free_snapshot is not None
        current_fingerprint = compute_source_snapshot(tiny_git_repo).fingerprint
        import dataclasses

        patched = dataclasses.replace(
            stale_free_snapshot, source_snapshot_fingerprint=current_fingerprint
        )
        write_coverage_snapshot(patched, repo_root=tiny_git_repo)

        result = check_coverage_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "project_version" in result.detail


class TestMeasureCoverageCliCommand:
    """Fase 10C section 10 - the `credlens release measure-coverage` CLI
    wiring itself (argparse flags -> `build_coverage_snapshot` ->
    `write_coverage_snapshot`), never exercised end-to-end before. Always
    `monkeypatch.chdir` into an isolated `tmp_path` git repo - this
    command reads/writes relative to the CURRENT directory, and must
    never touch the real repo's own `reports/release/coverage_snapshot.
    json` evidence file."""

    def test_writes_a_snapshot_with_the_new_evidence_fields(
        self, tiny_git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from credlens.cli import main

        coverage_json = tiny_git_repo / "coverage.json"
        coverage_json.write_text(
            json.dumps(
                {
                    "totals": {
                        "percent_covered": 96.5,
                        "num_statements": 1000,
                        "covered_lines": 965,
                        "missing_lines": 35,
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.chdir(tiny_git_repo)

        exit_code = main(
            [
                "release",
                "measure-coverage",
                "--coverage-json",
                "coverage.json",
                "--test-count",
                "1699",
                "--pytest-command",
                _REAL_COMMAND,
                "--pytest-exit-code",
                "0",
                "--json",
            ]
        )

        assert exit_code == 0
        written = json.loads(
            (tiny_git_repo / "reports/release/coverage_snapshot.json").read_text(encoding="utf-8")
        )
        assert written["test_count"] == 1699
        assert written["command"] == _REAL_COMMAND
        assert written["pytest_exit_code"] == 0

    def test_missing_coverage_json_returns_nonzero_exit(
        self, tiny_git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from credlens.cli import main

        monkeypatch.chdir(tiny_git_repo)
        exit_code = main(
            [
                "release",
                "measure-coverage",
                "--coverage-json",
                "does_not_exist.json",
                "--test-count",
                "1",
                "--pytest-command",
                _REAL_COMMAND,
                "--pytest-exit-code",
                "0",
            ]
        )
        assert exit_code == 1


class TestMonitoringDetectionGate:
    _DETECTION_PASS: ClassVar[dict[str, float]] = {
        "blocked_input_recall": 1.0,
        "raw_data_quality_detection_rate": 1.0,
        "strong_drift_detection_rate": 1.0,
        "overall_applicable_scenario_detection_rate": 1.0,
    }
    _FALSE_ALERT_PASS: ClassVar[dict[str, float]] = {
        "high_severity_false_alert_rate": 0.0,
        "combined_material_false_alert_rate": 0.03,
    }

    def test_missing_evidence_fails(self, tiny_git_repo: Path) -> None:
        from credlens.release.monitoring_gate import check_monitoring_detection_gate

        result = check_monitoring_detection_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"

    def test_passing_evidence_passes(self, tiny_git_repo: Path) -> None:
        from credlens.release.monitoring_gate import (
            check_monitoring_detection_gate,
            write_detection_evidence,
            write_false_alert_evidence,
        )

        write_detection_evidence(self._DETECTION_PASS, repo_root=tiny_git_repo)
        write_false_alert_evidence(self._FALSE_ALERT_PASS, repo_root=tiny_git_repo)
        result = check_monitoring_detection_gate(repo_root=tiny_git_repo)
        assert result.status == "pass"

    def test_low_detection_rate_fails(self, tiny_git_repo: Path) -> None:
        from credlens.release.monitoring_gate import (
            check_monitoring_detection_gate,
            write_detection_evidence,
            write_false_alert_evidence,
        )

        bad_detection = {**self._DETECTION_PASS, "overall_applicable_scenario_detection_rate": 0.5}
        write_detection_evidence(bad_detection, repo_root=tiny_git_repo)
        write_false_alert_evidence(self._FALSE_ALERT_PASS, repo_root=tiny_git_repo)
        result = check_monitoring_detection_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "overall_applicable_scenario_detection_rate" in result.detail

    def test_high_severity_false_alert_fails(self, tiny_git_repo: Path) -> None:
        from credlens.release.monitoring_gate import (
            check_monitoring_detection_gate,
            write_detection_evidence,
            write_false_alert_evidence,
        )

        bad_false_alerts = {**self._FALSE_ALERT_PASS, "high_severity_false_alert_rate": 0.05}
        write_detection_evidence(self._DETECTION_PASS, repo_root=tiny_git_repo)
        write_false_alert_evidence(bad_false_alerts, repo_root=tiny_git_repo)
        result = check_monitoring_detection_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "high_severity_false_alert_rate" in result.detail

    def test_low_blocked_input_recall_fails(self, tiny_git_repo: Path) -> None:
        from credlens.release.monitoring_gate import (
            check_monitoring_detection_gate,
            write_detection_evidence,
            write_false_alert_evidence,
        )

        bad_detection = {**self._DETECTION_PASS, "blocked_input_recall": 0.5}
        write_detection_evidence(bad_detection, repo_root=tiny_git_repo)
        write_false_alert_evidence(self._FALSE_ALERT_PASS, repo_root=tiny_git_repo)
        result = check_monitoring_detection_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "blocked_input_recall" in result.detail

    def test_low_raw_data_quality_detection_rate_fails(self, tiny_git_repo: Path) -> None:
        from credlens.release.monitoring_gate import (
            check_monitoring_detection_gate,
            write_detection_evidence,
            write_false_alert_evidence,
        )

        bad_detection = {**self._DETECTION_PASS, "raw_data_quality_detection_rate": 0.5}
        write_detection_evidence(bad_detection, repo_root=tiny_git_repo)
        write_false_alert_evidence(self._FALSE_ALERT_PASS, repo_root=tiny_git_repo)
        result = check_monitoring_detection_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "raw_data_quality_detection_rate" in result.detail

    def test_low_strong_drift_detection_rate_fails(self, tiny_git_repo: Path) -> None:
        from credlens.release.monitoring_gate import (
            check_monitoring_detection_gate,
            write_detection_evidence,
            write_false_alert_evidence,
        )

        bad_detection = {**self._DETECTION_PASS, "strong_drift_detection_rate": 0.5}
        write_detection_evidence(bad_detection, repo_root=tiny_git_repo)
        write_false_alert_evidence(self._FALSE_ALERT_PASS, repo_root=tiny_git_repo)
        result = check_monitoring_detection_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "strong_drift_detection_rate" in result.detail

    def test_high_combined_material_false_alert_rate_fails(self, tiny_git_repo: Path) -> None:
        from credlens.release.monitoring_gate import (
            check_monitoring_detection_gate,
            write_detection_evidence,
            write_false_alert_evidence,
        )

        bad_false_alerts = {**self._FALSE_ALERT_PASS, "combined_material_false_alert_rate": 0.5}
        write_detection_evidence(self._DETECTION_PASS, repo_root=tiny_git_repo)
        write_false_alert_evidence(bad_false_alerts, repo_root=tiny_git_repo)
        result = check_monitoring_detection_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "combined_material_false_alert_rate" in result.detail

    def test_stale_evidence_fails(self, tiny_git_repo: Path) -> None:
        from credlens.release.monitoring_gate import (
            check_monitoring_detection_gate,
            write_detection_evidence,
            write_false_alert_evidence,
        )

        write_detection_evidence(self._DETECTION_PASS, repo_root=tiny_git_repo)
        write_false_alert_evidence(self._FALSE_ALERT_PASS, repo_root=tiny_git_repo)
        (tiny_git_repo / "a.txt").write_text("changed after measuring detection", encoding="utf-8")
        result = check_monitoring_detection_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "STALE" in result.detail


class TestReleaseErrata:
    def test_build_and_write_errata_roundtrip(self, tmp_path: Path) -> None:
        from credlens.release.errata import (
            build_rc1_acceptance_errata,
            load_release_errata,
            write_release_errata,
        )

        entry = build_rc1_acceptance_errata(
            measured_coverage_percent=94.0, measured_scenario_detection_rate=0.5
        )
        write_release_errata(entry, repo_root=tmp_path)
        loaded = load_release_errata(repo_root=tmp_path)
        assert len(loaded) == 1
        assert loaded[0]["original_decision"] == "release_candidate_ready_with_limitations"
        assert loaded[0]["corrected_decision"] == "release_candidate_not_ready"
        assert "coverage_below_required_threshold" in loaded[0]["blockers"]

    def test_errata_is_append_only(self, tmp_path: Path) -> None:
        from credlens.release.errata import (
            build_rc1_acceptance_errata,
            load_release_errata,
            write_release_errata,
        )

        entry1 = build_rc1_acceptance_errata(
            measured_coverage_percent=94.0, measured_scenario_detection_rate=0.5
        )
        write_release_errata(entry1, repo_root=tmp_path)
        entry2 = build_rc1_acceptance_errata(
            measured_coverage_percent=96.0, measured_scenario_detection_rate=1.0
        )
        write_release_errata(entry2, repo_root=tmp_path)
        loaded = load_release_errata(repo_root=tmp_path)
        assert len(loaded) == 2

    def test_load_returns_empty_list_when_no_errata_file(self, tmp_path: Path) -> None:
        from credlens.release.errata import load_release_errata

        assert load_release_errata(repo_root=tmp_path) == []

    def test_write_raises_on_corrupt_existing_errata_file(self, tmp_path: Path) -> None:
        from credlens.release.errata import (
            ReleaseErrataError,
            build_rc1_acceptance_errata,
            write_release_errata,
        )

        path = tmp_path / "reports" / "release" / "release_errata.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not valid json", encoding="utf-8")
        entry = build_rc1_acceptance_errata(
            measured_coverage_percent=94.0, measured_scenario_detection_rate=0.5
        )
        with pytest.raises(ReleaseErrataError):
            write_release_errata(entry, repo_root=tmp_path)
