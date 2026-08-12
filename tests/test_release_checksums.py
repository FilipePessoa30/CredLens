"""Tests for credlens.release.checksums (Fase 12) - the canonical
release-asset checksum manifest that closes the "SHA256SUMS silently
went stale" gap found in the v1.0.0rc2 Pre-Release (see the module's
own docstring for the full root-cause history).

Every test here creates REAL files on disk and reads them back through
the real functions - no mocking of file I/O, so a regression in the
actual hashing/parsing/diffing logic cannot hide behind a stub."""

from __future__ import annotations

from pathlib import Path

import pytest

from credlens.release.checksums import (
    CANONICAL_RELEASE_ASSETS,
    CHECKSUMS_FILENAME,
    ChecksumError,
    compute_canonical_checksums,
    render_checksums_file,
    verify_release_checksums,
    write_release_checksums,
)
from credlens.release.integrity import run_release_integrity_checks


def _write_canonical_assets(repo_root: Path, *, content_suffix: str = "") -> None:
    for rel in CANONICAL_RELEASE_ASSETS:
        path = repo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"content of {rel}{content_suffix}\n", encoding="utf-8")


class TestComputeCanonicalChecksums:
    def test_raises_when_an_asset_is_missing(self, tmp_path: Path) -> None:
        with pytest.raises(ChecksumError, match="Missing canonical release asset"):
            compute_canonical_checksums(tmp_path)

    def test_returns_one_entry_per_canonical_asset_in_declared_order(self, tmp_path: Path) -> None:
        _write_canonical_assets(tmp_path)
        entries = compute_canonical_checksums(tmp_path)
        assert [e.path for e in entries] == list(CANONICAL_RELEASE_ASSETS)
        assert all(len(e.sha256) == 64 for e in entries)

    def test_hash_changes_when_content_changes(self, tmp_path: Path) -> None:
        _write_canonical_assets(tmp_path)
        before = {e.path: e.sha256 for e in compute_canonical_checksums(tmp_path)}
        target = tmp_path / CANONICAL_RELEASE_ASSETS[0]
        target.write_text(target.read_text(encoding="utf-8") + "extra byte", encoding="utf-8")
        after = {e.path: e.sha256 for e in compute_canonical_checksums(tmp_path)}
        assert before[CANONICAL_RELEASE_ASSETS[0]] != after[CANONICAL_RELEASE_ASSETS[0]]
        # Untouched assets must not be affected by an unrelated edit.
        for rel in CANONICAL_RELEASE_ASSETS[1:]:
            assert before[rel] == after[rel]

    def test_hash_identical_for_crlf_vs_lf_content(self, tmp_path: Path) -> None:
        """Real regression (Fase 12): SHA256SUMS generated on a Windows
        checkout (CRLF) of these JSON files failed `release validate` on
        the very first real GitHub Actions run against a Linux checkout
        of the SAME commit (LF, via this repo's own `.gitattributes`
        `eol=lf` checkout-time normalization) - for all three canonical
        assets simultaneously. Hashing must match `credlens.release.
        source_snapshot`'s own already-correct handling of this exact
        cross-platform problem."""
        rel = CANONICAL_RELEASE_ASSETS[0]
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        lf_content = '{"a": 1,\n "b": 2}\n'
        path.write_bytes(lf_content.encode("utf-8"))
        for other_rel in CANONICAL_RELEASE_ASSETS[1:]:
            other = tmp_path / other_rel
            other.parent.mkdir(parents=True, exist_ok=True)
            other.write_text("x", encoding="utf-8")
        lf_hash = {e.path: e.sha256 for e in compute_canonical_checksums(tmp_path)}[rel]

        path.write_bytes(lf_content.replace("\n", "\r\n").encode("utf-8"))
        crlf_hash = {e.path: e.sha256 for e in compute_canonical_checksums(tmp_path)}[rel]

        assert lf_hash == crlf_hash


class TestRenderChecksumsFile:
    def test_format_is_two_space_separated_hash_and_path(self, tmp_path: Path) -> None:
        _write_canonical_assets(tmp_path)
        entries = compute_canonical_checksums(tmp_path)
        rendered = render_checksums_file(entries)
        lines = rendered.splitlines()
        assert len(lines) == len(CANONICAL_RELEASE_ASSETS)
        for line, entry in zip(lines, entries, strict=True):
            assert line == f"{entry.sha256}  {entry.path}"

    def test_never_contains_crlf_regardless_of_platform(self, tmp_path: Path) -> None:
        _write_canonical_assets(tmp_path)
        rendered = render_checksums_file(compute_canonical_checksums(tmp_path))
        assert "\r" not in rendered

    def test_is_deterministic_across_repeated_calls(self, tmp_path: Path) -> None:
        _write_canonical_assets(tmp_path)
        entries = compute_canonical_checksums(tmp_path)
        assert render_checksums_file(entries) == render_checksums_file(entries)


class TestWriteReleaseChecksums:
    def test_writes_a_file_that_never_hashes_itself(self, tmp_path: Path) -> None:
        _write_canonical_assets(tmp_path)
        path = write_release_checksums(tmp_path)
        assert path.name == CHECKSUMS_FILENAME
        text = path.read_text(encoding="utf-8")
        assert CHECKSUMS_FILENAME not in text

    def test_raises_when_a_canonical_asset_is_missing(self, tmp_path: Path) -> None:
        with pytest.raises(ChecksumError):
            write_release_checksums(tmp_path)

    def test_is_idempotent_byte_for_byte_across_repeated_runs(self, tmp_path: Path) -> None:
        _write_canonical_assets(tmp_path)
        path = write_release_checksums(tmp_path)
        first_bytes = path.read_bytes()
        write_release_checksums(tmp_path)
        second_bytes = path.read_bytes()
        assert first_bytes == second_bytes

    def test_reflects_current_content_not_a_cached_value(self, tmp_path: Path) -> None:
        _write_canonical_assets(tmp_path)
        write_release_checksums(tmp_path)
        result_before = verify_release_checksums(tmp_path)
        assert result_before.status == "pass"

        target = tmp_path / CANONICAL_RELEASE_ASSETS[-1]
        target.write_text(target.read_text(encoding="utf-8") + "changed", encoding="utf-8")
        result_after_edit = verify_release_checksums(tmp_path)
        assert result_after_edit.status == "fail"

        write_release_checksums(tmp_path)
        result_after_regenerate = verify_release_checksums(tmp_path)
        assert result_after_regenerate.status == "pass"


class TestVerifyReleaseChecksums:
    """The core behavioral contract Fase 12 requires: generate assets,
    generate checksums, verify succeeds, mutate ONE byte of ONE asset,
    prove verification fails, regenerate, prove idempotency."""

    def test_full_lifecycle_generate_verify_mutate_fail_regenerate_pass(
        self, tmp_path: Path
    ) -> None:
        # 1. generate assets
        _write_canonical_assets(tmp_path)
        # 2. generate checksums
        write_release_checksums(tmp_path)
        # 3. validate with success
        assert verify_release_checksums(tmp_path).status == "pass"

        # 4. alter a single byte of one asset
        mutated_path = tmp_path / CANONICAL_RELEASE_ASSETS[2]
        original = mutated_path.read_bytes()
        mutated_path.write_bytes(original[:-1] + bytes([original[-1] ^ 0xFF]))

        # 5. prove the validation fails, and names the right file
        result = verify_release_checksums(tmp_path)
        assert result.status == "fail"
        assert CANONICAL_RELEASE_ASSETS[2] in result.stale_or_incorrect

        # 6. regenerate
        write_release_checksums(tmp_path)

        # 7. prove idempotency: verification now passes again, repeatedly
        assert verify_release_checksums(tmp_path).status == "pass"
        assert verify_release_checksums(tmp_path).status == "pass"

    def test_fails_when_checksums_file_is_absent(self, tmp_path: Path) -> None:
        _write_canonical_assets(tmp_path)
        result = verify_release_checksums(tmp_path)
        assert result.status == "fail"
        assert "No" in result.detail and CHECKSUMS_FILENAME in result.detail

    def test_fails_when_a_canonical_asset_is_missing_from_disk(self, tmp_path: Path) -> None:
        _write_canonical_assets(tmp_path)
        write_release_checksums(tmp_path)
        (tmp_path / CANONICAL_RELEASE_ASSETS[0]).unlink()
        result = verify_release_checksums(tmp_path)
        assert result.status == "fail"
        assert CANONICAL_RELEASE_ASSETS[0] in result.missing_assets_on_disk

    def test_fails_when_the_file_is_missing_a_declared_entry(self, tmp_path: Path) -> None:
        _write_canonical_assets(tmp_path)
        write_release_checksums(tmp_path)
        checksums_path = tmp_path / "reports" / "release" / CHECKSUMS_FILENAME
        lines = checksums_path.read_text(encoding="utf-8").splitlines()
        # Drop the entry for the first canonical asset - the file is
        # syntactically valid, just incomplete.
        trimmed = [line for line in lines if CANONICAL_RELEASE_ASSETS[0] not in line]
        checksums_path.write_text("\n".join(trimmed) + "\n", encoding="utf-8")

        result = verify_release_checksums(tmp_path)
        assert result.status == "fail"
        assert CANONICAL_RELEASE_ASSETS[0] in result.missing_from_file

    def test_fails_when_the_file_declares_an_unexpected_extra_entry(self, tmp_path: Path) -> None:
        _write_canonical_assets(tmp_path)
        write_release_checksums(tmp_path)
        checksums_path = tmp_path / "reports" / "release" / CHECKSUMS_FILENAME
        with checksums_path.open("a", encoding="utf-8") as handle:
            handle.write("0" * 64 + "  reports/release/not_a_real_asset.json\n")

        result = verify_release_checksums(tmp_path)
        assert result.status == "fail"
        assert "reports/release/not_a_real_asset.json" in result.undeclared_in_file

    def test_asset_missing_on_disk_is_reported_before_declared_set_diffing(
        self, tmp_path: Path
    ) -> None:
        """Asset absence is a more fundamental problem than a declared-set
        mismatch - it must be surfaced on its own, not conflated with
        'missing from file'."""
        _write_canonical_assets(tmp_path)
        write_release_checksums(tmp_path)
        (tmp_path / CANONICAL_RELEASE_ASSETS[1]).unlink()

        result = verify_release_checksums(tmp_path)
        assert result.status == "fail"
        assert result.missing_assets_on_disk == [CANONICAL_RELEASE_ASSETS[1]]
        assert result.missing_from_file == []
        assert result.undeclared_in_file == []


@pytest.mark.slow
class TestReleaseAssetsChecksumsGateOnTheRealRepo:
    def test_the_gate_appears_in_release_validate(self) -> None:
        report = run_release_integrity_checks(Path.cwd())
        names = {c.name for c in report.checks}
        assert "release_assets_checksums_verified" in names


class TestReleaseChecksumsCli:
    def test_credlens_release_checksums_writes_the_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from credlens.cli import main

        _write_canonical_assets(tmp_path)
        monkeypatch.chdir(tmp_path)
        exit_code = main(["release", "checksums"])
        assert exit_code == 0
        written = tmp_path / "reports" / "release" / CHECKSUMS_FILENAME
        assert written.is_file()
        assert verify_release_checksums(tmp_path).status == "pass"

    def test_credlens_release_checksums_fails_cleanly_when_an_asset_is_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from credlens.cli import main

        monkeypatch.chdir(tmp_path)
        exit_code = main(["release", "checksums"])
        assert exit_code == 1
