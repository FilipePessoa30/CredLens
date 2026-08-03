"""Tests for credlens.release.inventory (Fase 11A - Immutable Release
Identity and GitHub Publication Preflight): the canonical, classified
release inventory and its deterministic content fingerprint.

All git operations in this file run inside an isolated `tmp_path`
repository - never the real repository this test suite lives in.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from credlens.release.inventory import (
    SELF_REFERENTIAL_EVIDENCE,
    build_release_inventory,
    classify_path,
    compute_inventory_fingerprint,
)


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)


def _commit_all(root: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=root, check=True)


class TestClassifyPath:
    """Pure-function classification - no filesystem access, no git."""

    @pytest.mark.parametrize(
        "path,expected",
        [
            ("src/credlens/cli.py", "release_source"),
            ("dashboard/pages/1_Executive_Overview.py", "release_source"),
            ("tests/test_cli.py", "release_test"),
            ("warehouse/models/marts/mart_portfolio_monthly.sql", "release_sql"),
            ("warehouse/dbt_project.yml", "release_sql"),
            ("config/monitoring/thresholds.yml", "release_config"),
            ("contracts/operational/customers.yaml", "release_config"),
            (".github/workflows/ci.yml", "release_config"),
            ("pyproject.toml", "release_config"),
            ("uv.lock", "release_config"),
            ("LICENSE", "release_config"),
            ("data/metadata/file_manifest.csv", "release_config"),
            ("data/metadata/schemas/uci-default-credit.yaml", "release_config"),
            ("README.md", "release_documentation"),
            ("docs/data_contracts.md", "release_documentation"),
            ("notebooks/credit_portfolio_case_study.ipynb", "release_documentation"),
            ("PORTFOLIO.md", "release_documentation"),
            ("dashboard/demo_data/customers.parquet", "release_asset"),
            ("docs/assets/screenshot.png", "release_asset"),
            ("reports/model_validation/validation_report.md", "release_evidence"),
            ("reports/release/sbom.cyclonedx.json", "release_evidence"),
            ("data/warehouse/BUILD_x/warehouse.duckdb", "runtime_data_excluded"),
            ("data/synthetic/RUN_x/operational/customers.parquet", "runtime_data_excluded"),
            (
                "data/synthetic_truth/RUN_x/latent_customer_truth.parquet",
                "runtime_data_excluded",
            ),
            (
                "data/raw/uci_default_credit/default_of_credit_card_clients.csv",
                "runtime_data_excluded",
            ),
            ("warehouse/target/manifest.json", "runtime_data_excluded"),
            (
                "reports/modeling/quarantine/quarantine_20260101T000000.manifest.json",
                "temporary_excluded",
            ),
            ("reports/monitoring/runs/RUN_x/run.json", "temporary_excluded"),
            ("reports/monitoring/alerts/RUN_x.json", "temporary_excluded"),
            ("coverage.json", "temporary_excluded"),
            ("src/credlens/__pycache__/cli.cpython-311.pyc", "temporary_excluded"),
            (".env", "secret_excluded"),
            ("credentials.json", "secret_excluded"),
            ("id_rsa.pem", "secret_excluded"),
        ],
    )
    def test_classification(self, path: str, expected: str) -> None:
        classification, _reason = classify_path(path)
        assert classification == expected, f"{path}: got {classification!r}, expected {expected!r}"

    def test_env_example_is_not_a_secret(self) -> None:
        # The one deliberate exception .gitignore itself carves out
        # (`!.env.example`) - a template, never real credentials.
        classification, _ = classify_path(".env.example")
        assert classification != "secret_excluded"

    def test_unrecognized_path_is_unresolved_not_silently_dropped(self) -> None:
        classification, reason = classify_path("some/totally/novel/path.xyz")
        assert classification == "unresolved"
        assert "requires human review" in reason.lower()

    def test_windows_backslash_path_is_normalized(self) -> None:
        classification, _ = classify_path("src\\credlens\\cli.py")
        assert classification == "release_source"


class TestBuildReleaseInventoryRealRepo:
    @pytest.mark.slow
    def test_real_repo_produces_no_unresolved_entries(self) -> None:
        """Every one of this real repo's ~1,600 tracked files must match
        a classification rule - an `unresolved` entry here means the
        classifier has a real gap, not that the repo is unusual."""
        inventory = build_release_inventory(Path.cwd())
        assert inventory.unresolved == (), [e.path for e in inventory.unresolved]

    @pytest.mark.slow
    def test_real_repo_flags_the_known_ephemeral_tracked_directories(self) -> None:
        """Fase 11A's central finding: reports/modeling/quarantine/ and
        reports/monitoring/{runs,alerts}/ are tracked but never actually
        release content - real, accidentally-committed test byproducts."""
        inventory = build_release_inventory(Path.cwd())
        temp_paths = {e.path for e in inventory.entries if e.classification == "temporary_excluded"}
        assert any(p.startswith("reports/modeling/quarantine/") for p in temp_paths)
        assert any(p.startswith("reports/monitoring/runs/") for p in temp_paths)
        assert any(p.startswith("reports/monitoring/alerts/") for p in temp_paths)
        assert "coverage.json" in temp_paths

    @pytest.mark.slow
    def test_real_repo_fingerprint_is_stable_across_two_calls(self) -> None:
        first = build_release_inventory(Path.cwd())
        second = build_release_inventory(Path.cwd())
        assert first.fingerprint == second.fingerprint


class TestSelfReferenceExclusion:
    def test_self_referential_evidence_is_listed_but_not_hashed(self, tmp_path: Path) -> None:
        """Fase 11A section 7 - the release manifest/coverage snapshot/
        SBOM/etc. this same layer produces must be visible in the
        inventory (an operator can see they exist and are classified
        `release_evidence`) but excluded from the FINGERPRINT payload -
        otherwise writing any one of them would shift the fingerprint
        the others just stamped themselves with, an unresolvable cycle
        (the exact bug Phase 10B found for `source_snapshot`)."""
        _init_git_repo(tmp_path)
        (tmp_path / "reports" / "release").mkdir(parents=True)
        (tmp_path / "reports" / "release" / "release_manifest.json").write_text(
            '{"a": 1}', encoding="utf-8"
        )
        (tmp_path / "a.txt").write_text("stable content", encoding="utf-8")
        _commit_all(tmp_path, "init")

        before = build_release_inventory(tmp_path)
        assert any(e.path == "reports/release/release_manifest.json" for e in before.entries)

        # Writing the evidence file again with DIFFERENT content must
        # never change the fingerprint.
        (tmp_path / "reports" / "release" / "release_manifest.json").write_text(
            '{"a": 999, "different": true}', encoding="utf-8"
        )
        after = build_release_inventory(tmp_path)
        assert before.fingerprint == after.fingerprint

    def test_every_self_referential_path_is_excluded_from_fingerprint_payload(self) -> None:
        from credlens.release.inventory import InventoryEntry

        entries = [
            InventoryEntry(
                path=path,
                file_mode="100644",
                size_bytes=10,
                sha256="0" * 64,
                classification="release_evidence",
                reason="x",
                tracking_status="tracked",
                requires_human_review=False,
            )
            for path in SELF_REFERENTIAL_EVIDENCE
        ]
        fingerprint_with_evidence = compute_inventory_fingerprint(entries)
        fingerprint_without_any_entries = compute_inventory_fingerprint([])
        assert fingerprint_with_evidence == fingerprint_without_any_entries


class TestUntrackedFilesAreNotPresumedEphemeral:
    def test_untracked_release_worthy_file_enters_the_fingerprint(self, tmp_path: Path) -> None:
        """Fase 11A section 5 - an untracked file that looks like real
        release content (source, docs, config, screenshot) must enter
        the INTENDED inventory and fingerprint even before `git add`,
        never be silently treated as ephemeral."""
        _init_git_repo(tmp_path)
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        _commit_all(tmp_path, "init")

        before = build_release_inventory(tmp_path)

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "new_module.py").write_text("def f(): pass\n", encoding="utf-8")
        after = build_release_inventory(tmp_path)

        new_entry = next(e for e in after.entries if e.path == "src/new_module.py")
        assert new_entry.tracking_status == "untracked"
        assert new_entry.classification == "release_source"
        assert new_entry.requires_human_review is True
        assert before.fingerprint != after.fingerprint

    def test_index_is_never_touched_by_building_the_inventory(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        _commit_all(tmp_path, "init")
        (tmp_path / "b.txt").write_text("new untracked file", encoding="utf-8")

        build_release_inventory(tmp_path)

        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert staged.stdout.strip() == ""
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "?? b.txt" in status.stdout


class TestFingerprintStableAcrossACommit:
    """Fase 11A section 8 - the release content must not change simply
    because it was committed. Every git operation here runs inside
    `tmp_path`; this test never touches the real repository."""

    def test_content_fingerprint_identical_before_and_after_temp_commit(
        self, tmp_path: Path
    ) -> None:
        _init_git_repo(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")
        _commit_all(tmp_path, "initial commit")
        commit_before = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout.strip()

        # 2. Modify the working tree (uncommitted).
        (tmp_path / "src" / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
        # 3. Include a brand-new, untracked file in the intended inventory.
        (tmp_path / "src" / "extra.py").write_text("EXTRA = True\n", encoding="utf-8")

        # 4. Calculate the fingerprint against the DIRTY tree.
        before_commit = build_release_inventory(tmp_path)
        assert before_commit.needs_human_review  # the new untracked file

        # 5. Commit - ONLY inside this temp repository.
        _commit_all(tmp_path, "second commit: bump VALUE, add extra module")
        commit_after = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout.strip()

        # 6. Recalculate.
        after_commit = build_release_inventory(tmp_path)

        # 7. Same CONTENT fingerprint - committing didn't change what's
        # actually in the files, only how git records it.
        assert before_commit.fingerprint == after_commit.fingerprint
        # The file that was untracked before is tracked now, but its
        # bytes are identical - the fingerprint payload doesn't care.
        assert after_commit.needs_human_review == ()

        # 8. Commit METADATA changed separately (HEAD moved) - proving
        # this is a real commit, not a no-op, while content fingerprint
        # stayed fixed.
        assert commit_before != commit_after
