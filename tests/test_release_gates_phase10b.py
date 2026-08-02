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


class TestCoverageGate:
    def _write_fake_coverage_json(self, root: Path, *, percent: float) -> Path:
        path = root / "coverage.json"
        path.write_text(
            json.dumps(
                {
                    "totals": {
                        "percent_covered": percent,
                        "num_statements": 1000,
                        "covered_lines": int(percent * 10),
                    }
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_missing_snapshot_fails(self, tiny_git_repo: Path) -> None:
        from credlens.release.coverage_gate import check_coverage_gate

        result = check_coverage_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "No coverage snapshot" in result.detail

    def test_build_snapshot_requires_a_real_coverage_json(self, tiny_git_repo: Path) -> None:
        from credlens.release.coverage_gate import CoverageGateError, build_coverage_snapshot

        with pytest.raises(CoverageGateError):
            build_coverage_snapshot(tiny_git_repo / "nope.json", test_count=10)

    def test_build_snapshot_rejects_invalid_json(self, tiny_git_repo: Path) -> None:
        from credlens.release.coverage_gate import CoverageGateError, build_coverage_snapshot

        bad = tiny_git_repo / "coverage.json"
        bad.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(CoverageGateError):
            build_coverage_snapshot(bad, test_count=10, repo_root=tiny_git_repo)

    def test_build_snapshot_rejects_missing_totals_section(self, tiny_git_repo: Path) -> None:
        from credlens.release.coverage_gate import CoverageGateError, build_coverage_snapshot

        no_totals = tiny_git_repo / "coverage.json"
        no_totals.write_text(json.dumps({"files": {}}), encoding="utf-8")
        with pytest.raises(CoverageGateError):
            build_coverage_snapshot(no_totals, test_count=10, repo_root=tiny_git_repo)

    def test_snapshot_below_threshold_fails(self, tiny_git_repo: Path) -> None:
        from credlens.release.coverage_gate import (
            build_coverage_snapshot,
            check_coverage_gate,
            write_coverage_snapshot,
        )

        coverage_json = self._write_fake_coverage_json(tiny_git_repo, percent=80.0)
        snapshot = build_coverage_snapshot(coverage_json, test_count=42, repo_root=tiny_git_repo)
        write_coverage_snapshot(snapshot, repo_root=tiny_git_repo)
        result = check_coverage_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "80.00%" in result.detail

    def test_snapshot_meeting_threshold_passes(self, tiny_git_repo: Path) -> None:
        from credlens.release.coverage_gate import (
            build_coverage_snapshot,
            check_coverage_gate,
            write_coverage_snapshot,
        )

        coverage_json = self._write_fake_coverage_json(tiny_git_repo, percent=97.5)
        snapshot = build_coverage_snapshot(coverage_json, test_count=1599, repo_root=tiny_git_repo)
        write_coverage_snapshot(snapshot, repo_root=tiny_git_repo)
        result = check_coverage_gate(repo_root=tiny_git_repo)
        assert result.status == "pass"

    def test_stale_snapshot_fails_even_if_coverage_was_once_high(self, tiny_git_repo: Path) -> None:
        from credlens.release.coverage_gate import (
            build_coverage_snapshot,
            check_coverage_gate,
            write_coverage_snapshot,
        )

        coverage_json = self._write_fake_coverage_json(tiny_git_repo, percent=99.0)
        snapshot = build_coverage_snapshot(coverage_json, test_count=1, repo_root=tiny_git_repo)
        write_coverage_snapshot(snapshot, repo_root=tiny_git_repo)
        # Code changes AFTER the snapshot was measured.
        (tiny_git_repo / "a.txt").write_text("changed after measuring coverage", encoding="utf-8")
        result = check_coverage_gate(repo_root=tiny_git_repo)
        assert result.status == "fail"
        assert "STALE" in result.detail


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
