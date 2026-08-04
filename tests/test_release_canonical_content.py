"""Tests for credlens.release.canonical_content (Fase 11B): the shared
helpers `source_snapshot` and `inventory` both use to agree with git's
own storage policy (LF-normalized text, `core.filemode=false` mode)
instead of whatever a particular OS checkout happens to produce.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from credlens.release.canonical_content import (
    DEFAULT_FILE_MODE,
    canonicalize_content,
    git_tracked_file_modes,
)


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=root, check=True)


class TestCanonicalizeContent:
    def test_crlf_normalized_to_lf_for_a_text_path(self) -> None:
        raw = b"line one\r\nline two\r\nline three\r\n"
        assert canonicalize_content("src/module.py", raw) == b"line one\nline two\nline three\n"

    def test_lone_cr_normalized_to_lf(self) -> None:
        assert canonicalize_content("README.md", b"old mac\rstyle\r") == b"old mac\nstyle\n"

    def test_already_lf_content_is_unchanged(self) -> None:
        raw = b"line one\nline two\n"
        assert canonicalize_content("src/module.py", raw) == raw

    def test_binary_extension_is_never_normalized(self) -> None:
        raw = b"\x89PNG\r\n\x1a\n" + b"payload with a lone \r and a \r\n pair"
        assert canonicalize_content("docs/assets/screenshot.png", raw) == raw

    def test_content_with_a_nul_byte_is_treated_as_binary_regardless_of_extension(self) -> None:
        raw = b"looks like text\r\nbut has a \x00 in it\r\n"
        assert canonicalize_content("weird.py", raw) == raw

    def test_extension_matching_is_case_insensitive(self) -> None:
        raw = b"\x89PNG\r\ndata"
        assert canonicalize_content("SCREENSHOT.PNG", raw) == raw

    def test_empty_content_normalizes_to_empty(self) -> None:
        assert canonicalize_content("src/empty.py", b"") == b""


class TestGitTrackedFileModes:
    def test_returns_100644_for_a_freshly_committed_regular_file(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        _init_git_repo(tmp_path)

        modes = git_tracked_file_modes(tmp_path)
        assert modes["src/module.py"] == "100644"

    def test_untracked_file_is_absent_from_the_mapping(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        _init_git_repo(tmp_path)
        (tmp_path / "b.txt").write_text("untracked", encoding="utf-8")

        modes = git_tracked_file_modes(tmp_path)
        assert "a.txt" in modes
        assert "b.txt" not in modes

    def test_paths_use_forward_slashes(self, tmp_path: Path) -> None:
        (tmp_path / "sub" / "nested").mkdir(parents=True)
        (tmp_path / "sub" / "nested" / "file.txt").write_text("x", encoding="utf-8")
        _init_git_repo(tmp_path)

        modes = git_tracked_file_modes(tmp_path)
        assert "sub/nested/file.txt" in modes
        assert not any("\\" in path for path in modes)


class TestDefaultFileMode:
    def test_default_file_mode_is_the_git_regular_file_mode(self) -> None:
        assert DEFAULT_FILE_MODE == "100644"
