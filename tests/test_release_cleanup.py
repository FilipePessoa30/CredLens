"""Tests for credlens.release.cleanup (Fase 11B Gate B) - the
tracked-but-ephemeral index cleanup manifest and its execution. Every
git operation in this file runs inside an isolated `tmp_path`
repository - never the real repository this test suite lives in.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from credlens.release.cleanup import (
    CleanupManifestError,
    build_cleanup_manifest,
    execute_cleanup,
    write_cleanup_manifest,
)


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)


def _commit_all(root: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=root, check=True)


def _staged_names(root: Path) -> str:
    return subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=root, capture_output=True, text=True
    ).stdout


def _tracked(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    )
    return set(result.stdout.splitlines())


def _make_ephemeral_repo(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

    quarantine_dir = root / "reports" / "modeling" / "quarantine"
    quarantine_dir.mkdir(parents=True)
    for i in range(3):
        (quarantine_dir / f"quarantine_{i}.manifest.json").write_text("{}", encoding="utf-8")

    alerts_dir = root / "reports" / "monitoring" / "alerts"
    alerts_dir.mkdir(parents=True)
    for i in range(2):
        (alerts_dir / f"RUN_{i}.json").write_text("{}", encoding="utf-8")

    runs_dir = root / "reports" / "monitoring" / "runs"
    for i in range(2):
        run_dir = runs_dir / f"RUN_x_{i}"
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text("{}", encoding="utf-8")

    # The one path under runs/ that must NEVER be proposed for removal.
    reference_dir = runs_dir / "BATCHSET_REF_MODEL_x"
    reference_dir.mkdir(parents=True)
    (reference_dir / "batch_manifest.json").write_text('{"batches": []}', encoding="utf-8")

    (root / "coverage.json").write_text('{"totals": {}}', encoding="utf-8")

    _init_git_repo(root)
    _commit_all(root, "init")


class TestBuildCleanupManifest:
    def test_groups_and_counts_match_the_ephemeral_fixtures(self, tmp_path: Path) -> None:
        _make_ephemeral_repo(tmp_path)

        manifest = build_cleanup_manifest(tmp_path)

        by_id = {g.group_id: g for g in manifest.groups}
        assert by_id["modeling_quarantine"].quantity == 3
        assert by_id["monitoring_alerts"].quantity == 2
        assert by_id["monitoring_runs"].quantity == 2
        assert by_id["coverage_json"].quantity == 1
        assert manifest.total_quantity == 8

    def test_batchset_reference_fixture_is_never_included(self, tmp_path: Path) -> None:
        _make_ephemeral_repo(tmp_path)

        manifest = build_cleanup_manifest(tmp_path)

        assert not any(
            path.startswith("reports/monitoring/runs/BATCHSET_") for path in manifest.all_paths
        ), "the load-bearing reference fixture must never be proposed for removal"

    def test_release_source_and_reference_fixture_are_not_in_any_group(
        self, tmp_path: Path
    ) -> None:
        _make_ephemeral_repo(tmp_path)

        manifest = build_cleanup_manifest(tmp_path)

        assert "src/module.py" not in manifest.all_paths
        assert (
            "reports/monitoring/runs/BATCHSET_REF_MODEL_x/batch_manifest.json"
            not in manifest.all_paths
        )

    def test_aggregate_hash_is_stable_across_two_calls(self, tmp_path: Path) -> None:
        _make_ephemeral_repo(tmp_path)

        first = build_cleanup_manifest(tmp_path)
        second = build_cleanup_manifest(tmp_path)

        first_hashes = {g.group_id: g.aggregate_hash for g in first.groups}
        second_hashes = {g.group_id: g.aggregate_hash for g in second.groups}
        assert first_hashes == second_hashes

    def test_total_size_bytes_is_positive_and_sums_group_totals(self, tmp_path: Path) -> None:
        _make_ephemeral_repo(tmp_path)

        manifest = build_cleanup_manifest(tmp_path)

        assert manifest.total_size_bytes > 0
        assert manifest.total_size_bytes == sum(g.total_size_bytes for g in manifest.groups)

    def test_planned_command_never_recurses_over_the_raw_prefix(self, tmp_path: Path) -> None:
        """The `monitoring_runs` group's prefix also contains the
        BATCHSET_ reference fixture - a bare `git rm -r --cached --
        reports/monitoring/runs/` would remove it too. The displayed
        command must reflect the actual, exact-path-list removal."""
        _make_ephemeral_repo(tmp_path)

        manifest = build_cleanup_manifest(tmp_path)
        runs_group = next(g for g in manifest.groups if g.group_id == "monitoring_runs")

        assert "-r" not in runs_group.planned_command()
        assert "reports/monitoring/runs/" not in runs_group.planned_command().split("<")[0]


class TestWriteCleanupManifest:
    def test_writes_valid_json_with_expected_fields(self, tmp_path: Path) -> None:
        _make_ephemeral_repo(tmp_path)
        manifest = build_cleanup_manifest(tmp_path)

        out_path = write_cleanup_manifest(manifest, tmp_path)

        assert out_path == tmp_path / "reports" / "release" / "tracked_cleanup_manifest.json"
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["total_quantity"] == 8
        for group in data["groups"]:
            for field in (
                "group_id",
                "path",
                "classification",
                "quantity",
                "size_bytes",
                "hash",
                "reason",
                "reproducible",
                "stays_on_disk",
                "gitignore_rule",
                "planned_command",
            ):
                assert field in group, f"missing field {field!r} in group {group['group_id']!r}"
            assert group["stays_on_disk"] is True

    def test_writing_the_manifest_never_touches_the_index(self, tmp_path: Path) -> None:
        _make_ephemeral_repo(tmp_path)
        manifest = build_cleanup_manifest(tmp_path)

        write_cleanup_manifest(manifest, tmp_path)

        assert _staged_names(tmp_path).strip() == ""


class TestExecuteCleanupDryRun:
    def test_dry_run_never_touches_the_index_or_disk(self, tmp_path: Path) -> None:
        _make_ephemeral_repo(tmp_path)
        manifest = build_cleanup_manifest(tmp_path)
        tracked_before = _tracked(tmp_path)

        result = execute_cleanup(manifest, tmp_path, dry_run=True)

        assert result.dry_run is True
        assert len(result.removed_paths) == 8
        assert _staged_names(tmp_path).strip() == ""
        assert _tracked(tmp_path) == tracked_before
        for path in manifest.all_paths:
            assert (tmp_path / path).is_file()

    def test_refuses_when_tracked_paths_have_drifted_since_the_manifest_was_built(
        self, tmp_path: Path
    ) -> None:
        _make_ephemeral_repo(tmp_path)
        manifest = build_cleanup_manifest(tmp_path)

        # A new ephemeral file appears after the manifest was built.
        new_alert = tmp_path / "reports" / "monitoring" / "alerts" / "RUN_new.json"
        new_alert.write_text("{}", encoding="utf-8")
        _commit_all(tmp_path, "add a new alert after the manifest was built")

        with pytest.raises(CleanupManifestError, match="drifted"):
            execute_cleanup(manifest, tmp_path, dry_run=False)


class TestExecuteCleanupReal:
    def test_removes_only_the_planned_paths_from_the_index_and_preserves_them_on_disk(
        self, tmp_path: Path
    ) -> None:
        _make_ephemeral_repo(tmp_path)
        manifest = build_cleanup_manifest(tmp_path)
        tracked_before = _tracked(tmp_path)

        result = execute_cleanup(manifest, tmp_path, dry_run=False)

        assert result.dry_run is False
        assert result.index_diff_matches_plan is True
        assert set(result.removed_paths) == set(manifest.all_paths)

        # Every removed path stays on disk with its content intact.
        for path in manifest.all_paths:
            assert (tmp_path / path).is_file()
        assert (tmp_path / "reports/monitoring/alerts/RUN_0.json").read_text(
            encoding="utf-8"
        ) == "{}"

        # The staged diff shows exactly the planned removals - nothing else.
        staged = _staged_names(tmp_path)
        staged_paths = {line for line in staged.splitlines() if line}
        assert staged_paths == set(manifest.all_paths)

        # Untouched paths (release source, the reference fixture) are
        # still tracked and unaffected.
        tracked_after_staging = _tracked(tmp_path)
        assert "src/module.py" in tracked_after_staging
        assert (
            "reports/monitoring/runs/BATCHSET_REF_MODEL_x/batch_manifest.json"
            in tracked_after_staging
        )
        # `git ls-files` reflects the index immediately - exactly the
        # planned paths (and nothing else) are gone from it now.
        assert tracked_before - tracked_after_staging == set(manifest.all_paths)

    def test_refuses_against_an_already_dirty_index(self, tmp_path: Path) -> None:
        _make_ephemeral_repo(tmp_path)
        manifest = build_cleanup_manifest(tmp_path)
        (tmp_path / "src" / "other.py").write_text("z = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "src/other.py"], cwd=tmp_path, check=True)

        with pytest.raises(CleanupManifestError, match="dirty index"):
            execute_cleanup(manifest, tmp_path, dry_run=False)

        subprocess.run(["git", "reset"], cwd=tmp_path, check=True)

    def test_no_path_outside_the_allowlist_is_ever_touched(self, tmp_path: Path) -> None:
        _make_ephemeral_repo(tmp_path)
        manifest = build_cleanup_manifest(tmp_path)

        execute_cleanup(manifest, tmp_path, dry_run=False)

        staged_paths = {line for line in _staged_names(tmp_path).splitlines() if line}
        unexpected = staged_paths - set(manifest.all_paths)
        assert unexpected == set()


@pytest.mark.slow
class TestRealRepoCleanupManifest:
    def test_real_repo_manifest_builds_and_excludes_the_reference_fixture(self) -> None:
        """Gate B's own `git rm --cached` already ran against this real
        repo, so `total_quantity` is legitimately 0 now (nothing left
        to clean up) - this test guards the MACHINERY (correct group
        structure, the BATCHSET_ carve-out, no crash), not a nonzero
        count, which would only reappear if these paths got re-tracked."""
        manifest = build_cleanup_manifest(Path.cwd())

        assert manifest.total_quantity >= 0
        assert not any(
            path.startswith("reports/monitoring/runs/BATCHSET_") for path in manifest.all_paths
        )
        by_id = {g.group_id: g for g in manifest.groups}
        assert set(by_id) == {
            "modeling_quarantine",
            "monitoring_alerts",
            "monitoring_runs",
            "coverage_json",
        }
