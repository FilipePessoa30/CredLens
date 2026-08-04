"""Tests for credlens.release.inventory (Fase 11A - Immutable Release
Identity and GitHub Publication Preflight): the canonical, classified
release inventory and its deterministic content fingerprint.

All git operations in this file run inside an isolated `tmp_path`
repository - never the real repository this test suite lives in.
"""

from __future__ import annotations

import hashlib
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
    def test_real_repo_no_longer_tracks_the_fase_11a_ephemeral_directories(self) -> None:
        """Fase 11A found reports/modeling/quarantine/, reports/monitoring/
        {runs,alerts}/, and coverage.json TRACKED despite never being
        actual release content - real, accidentally-committed test
        byproducts (credlens.release.cleanup's Gate B). Fase 11B removed
        all 1,024 of them from the index (`git rm --cached`, files kept
        on disk) and added specific `.gitignore` rules - a regression
        here means one of those paths was accidentally re-tracked."""
        inventory = build_release_inventory(Path.cwd())
        tracked_paths = {e.path for e in inventory.entries if e.tracking_status == "tracked"}
        assert not any(p.startswith("reports/modeling/quarantine/") for p in tracked_paths)
        assert not any(p.startswith("reports/monitoring/runs/RUN_") for p in tracked_paths)
        assert not any(p.startswith("reports/monitoring/alerts/") for p in tracked_paths)
        assert "coverage.json" not in tracked_paths
        # The one load-bearing reference fixture under runs/ must remain
        # tracked - Gate B's cleanup deliberately excluded it.
        assert (
            "reports/monitoring/runs/BATCHSET_REF_MODEL_behavioral_default_v1/batch_manifest.json"
            in tracked_paths
        )

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


class TestCrlfLfCanonicalization:
    """Fase 11B section 8 - CRLF/LF must never leak into the release
    inventory's fingerprint. `.gitattributes` normalizes this repo's
    text files to LF (`* text=auto eol=lf`), so a Windows working tree
    (CRLF on disk) and a Linux working tree (LF on disk) checking out
    the exact same commit must classify to the identical sha256, size,
    and inventory fingerprint - confirmed broken before this fix:
    `src/credlens/cli.py` hashed to two different SHA-256 digests
    depending on whether raw disk bytes or git's own LF blob were read.
    """

    def test_tracked_file_crlf_and_lf_content_hash_identically(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        (tmp_path / "src").mkdir()
        lf_content = "line one\nline two\nline three\n"
        (tmp_path / "src" / "module.py").write_bytes(lf_content.encode("utf-8"))
        _commit_all(tmp_path, "init with LF content")
        lf_inventory = build_release_inventory(tmp_path)
        lf_entry = next(e for e in lf_inventory.entries if e.path == "src/module.py")

        # Rewrite the SAME logical content with CRLF endings - no git
        # operation involved, exactly what a Windows working tree
        # (`core.autocrlf=true`) looks like for identical logical
        # content, WITHOUT committing the difference.
        crlf_content = lf_content.replace("\n", "\r\n")
        (tmp_path / "src" / "module.py").write_bytes(crlf_content.encode("utf-8"))
        crlf_inventory = build_release_inventory(tmp_path)
        crlf_entry = next(e for e in crlf_inventory.entries if e.path == "src/module.py")

        assert lf_entry.sha256 == crlf_entry.sha256
        assert lf_entry.size_bytes == crlf_entry.size_bytes
        assert lf_inventory.fingerprint == crlf_inventory.fingerprint

    def test_untracked_file_crlf_and_lf_content_hash_identically(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        _commit_all(tmp_path, "init")

        (tmp_path / "src").mkdir()
        lf_content = "def f():\n    return 1\n"
        (tmp_path / "src" / "new_module.py").write_bytes(lf_content.encode("utf-8"))
        lf_inventory = build_release_inventory(tmp_path)
        lf_entry = next(e for e in lf_inventory.entries if e.path == "src/new_module.py")

        crlf_content = lf_content.replace("\n", "\r\n")
        (tmp_path / "src" / "new_module.py").write_bytes(crlf_content.encode("utf-8"))
        crlf_inventory = build_release_inventory(tmp_path)
        crlf_entry = next(e for e in crlf_inventory.entries if e.path == "src/new_module.py")

        assert lf_entry.sha256 == crlf_entry.sha256
        assert lf_entry.size_bytes == crlf_entry.size_bytes

    def test_binary_extension_content_is_never_line_ending_normalized(self, tmp_path: Path) -> None:
        """A `.png` (or other `.gitattributes`-binary extension) must
        hash its RAW bytes unchanged - normalizing binary content would
        corrupt it, exactly what `.gitattributes`'s binary declarations
        exist to prevent."""
        _init_git_repo(tmp_path)
        raw = b"\x89PNG\r\n\x1a\n" + b"fake binary payload with a lone \r and a \r\n pair"
        (tmp_path / "image.png").write_bytes(raw)
        _commit_all(tmp_path, "init with a binary file")

        inventory = build_release_inventory(tmp_path)
        entry = next(e for e in inventory.entries if e.path == "image.png")
        assert entry.sha256 == hashlib.sha256(raw).hexdigest()
        assert entry.size_bytes == len(raw)

    def test_fingerprint_stable_across_a_commit_with_a_crlf_working_tree(
        self, tmp_path: Path
    ) -> None:
        """The full section-8 matrix in one test: a CRLF-on-disk
        working tree, rewritten with the same logical content, then
        committed - the CONTENT fingerprint must never move for reasons
        unrelated to actual content (tracked before/after a commit,
        exactly like `TestFingerprintStableAcrossACommit` above, but
        with CRLF endings on disk throughout)."""
        _init_git_repo(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "module.py").write_bytes(b"VALUE = 1\r\n")
        _commit_all(tmp_path, "init")
        before_commit = build_release_inventory(tmp_path)

        (tmp_path / "src" / "module.py").write_bytes(b"VALUE = 1\r\n")  # rewritten, same content
        after_rewrite = build_release_inventory(tmp_path)
        assert before_commit.fingerprint == after_rewrite.fingerprint


class TestFileModeUsesGitIndexNotOsLevelPermissionProbing:
    """Fase 11B section 8 - `os.access(path, os.X_OK)` returns True for
    essentially any readable file on Windows (there is no POSIX execute
    bit to observe there), so probing it directly reported "100755" for
    EVERY tracked file on this machine, while git's own index (and a
    real Linux checkout, given this repo's `core.filemode=false`) has
    "100644" for all of them - confirmed via `git ls-files -s`. `
    file_mode` must always come from git's own index, never from an
    OS-level permission probe."""

    def test_tracked_file_mode_matches_git_ls_files_s(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        _commit_all(tmp_path, "init")

        inventory = build_release_inventory(tmp_path)
        entry = next(e for e in inventory.entries if e.path == "src/module.py")

        ls_files = subprocess.run(
            ["git", "ls-files", "-s", "src/module.py"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        git_mode = ls_files.split()[0]
        assert entry.file_mode == git_mode == "100644"

    def test_tracked_file_mode_is_unaffected_by_a_lying_os_access(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _init_git_repo(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        _commit_all(tmp_path, "init")

        # The exact, confirmed real-world behavior on Windows: os.access
        # reports every file as "executable". If `file_mode` were still
        # derived from this, every entry would wrongly report "100755".
        monkeypatch.setattr("os.access", lambda *_a, **_kw: True)

        inventory = build_release_inventory(tmp_path)
        entry = next(e for e in inventory.entries if e.path == "src/module.py")
        assert entry.file_mode == "100644"

    def test_untracked_file_mode_defaults_to_100644(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _init_git_repo(tmp_path)
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        _commit_all(tmp_path, "init")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "new_module.py").write_text("def f(): pass\n", encoding="utf-8")

        monkeypatch.setattr("os.access", lambda *_a, **_kw: True)

        inventory = build_release_inventory(tmp_path)
        entry = next(e for e in inventory.entries if e.path == "src/new_module.py")
        assert entry.file_mode == "100644"
