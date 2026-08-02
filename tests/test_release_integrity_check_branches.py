"""Branch-coverage tests for `credlens.release.integrity`'s individual
`_check_*` functions (Phase 10B section 4.3: "caminhos de erro, inputs
inválidos, artefatos ausentes"). The existing `TestRunReleaseIntegrityChecksOnRealRepo`
suite only ever exercises the PASS branch of every check (the real repo
is, correctly, clean) - these tests construct isolated fixtures that hit
every fail/warning branch instead.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from credlens.release.integrity import (
    _check_bilingual_reports_present,
    _check_ci_workflow_no_masking,
    _check_direct_dependencies_have_licenses,
    _check_license_present,
    _check_lockfile_present,
    _check_model_artifacts_present,
    _check_no_large_tracked_files,
    _check_no_pii_like_columns_in_demo_data,
    _check_no_secrets,
    _check_version_declared,
)


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=root, check=True)


class TestCheckVersionDeclared:
    def test_pass_when_version_present(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('version = "1.2.3"\n', encoding="utf-8")
        check = _check_version_declared(tmp_path)
        assert check.status == "pass"
        assert "1.2.3" in check.detail

    def test_fail_when_no_version_line(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
        check = _check_version_declared(tmp_path)
        assert check.status == "fail"

    def test_fail_when_pyproject_toml_missing(self, tmp_path: Path) -> None:
        """Must degrade to a `fail` IntegrityCheck, never raise
        FileNotFoundError and crash the whole integrity report."""
        check = _check_version_declared(tmp_path)
        assert check.status == "fail"


class TestCheckLockfilePresent:
    def test_pass_when_lockfile_present(self, tmp_path: Path) -> None:
        (tmp_path / "uv.lock").write_text("", encoding="utf-8")
        assert _check_lockfile_present(tmp_path).status == "pass"

    def test_fail_when_lockfile_missing(self, tmp_path: Path) -> None:
        assert _check_lockfile_present(tmp_path).status == "fail"


class TestCheckLicensePresent:
    def test_pass_when_license_present_and_nonempty(self, tmp_path: Path) -> None:
        (tmp_path / "LICENSE").write_text("MIT License", encoding="utf-8")
        assert _check_license_present(tmp_path).status == "pass"

    def test_fail_when_license_missing(self, tmp_path: Path) -> None:
        assert _check_license_present(tmp_path).status == "fail"

    def test_fail_when_license_empty(self, tmp_path: Path) -> None:
        (tmp_path / "LICENSE").write_text("", encoding="utf-8")
        assert _check_license_present(tmp_path).status == "fail"


class TestCheckNoSecrets:
    def test_pass_on_clean_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        _init_git_repo(tmp_path)
        assert _check_no_secrets(tmp_path).status == "pass"

    def test_fail_on_aws_key_shaped_string(self, tmp_path: Path) -> None:
        (tmp_path / "leak.py").write_text('key = "AKIAABCDEFGHIJKLMNOP"\n', encoding="utf-8")
        _init_git_repo(tmp_path)
        check = _check_no_secrets(tmp_path)
        assert check.status == "fail"
        assert "aws_access_key_id" in check.detail

    def test_fail_on_private_key_header(self, tmp_path: Path) -> None:
        (tmp_path / "key.pem").write_text(
            "-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n", encoding="utf-8"
        )
        _init_git_repo(tmp_path)
        check = _check_no_secrets(tmp_path)
        assert check.status == "fail"
        assert "generic_private_key" in check.detail

    def test_excluded_directories_are_never_scanned(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "fixture.py").write_text(
            'key = "AKIAABCDEFGHIJKLMNOP"\n', encoding="utf-8"
        )
        _init_git_repo(tmp_path)
        assert _check_no_secrets(tmp_path).status == "pass"


class TestCheckNoLargeTrackedFiles:
    def test_pass_when_all_files_small(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("small", encoding="utf-8")
        _init_git_repo(tmp_path)
        assert _check_no_large_tracked_files(tmp_path).status == "pass"

    def test_warning_when_a_tracked_file_exceeds_10mib(self, tmp_path: Path) -> None:
        (tmp_path / "big.bin").write_bytes(b"0" * (11 * 1024 * 1024))
        _init_git_repo(tmp_path)
        check = _check_no_large_tracked_files(tmp_path)
        assert check.status == "warning"
        assert "big.bin" in check.detail


class TestCheckDirectDependenciesHaveLicenses:
    def test_pass_when_no_pyproject_toml_at_all(self, tmp_path: Path) -> None:
        # No direct dependency roles can be resolved without pyproject.toml
        # -> nothing is "direct" -> vacuously no unresolved DIRECT license.
        check = _check_direct_dependencies_have_licenses(tmp_path)
        assert check.status == "pass"


class TestCheckNoPiiLikeColumns:
    def test_warning_when_demo_dir_missing(self, tmp_path: Path) -> None:
        check = _check_no_pii_like_columns_in_demo_data(tmp_path)
        assert check.status == "warning"

    def test_fail_when_a_parquet_has_a_pii_like_column(self, tmp_path: Path) -> None:
        import pandas as pd

        demo_dir = tmp_path / "dashboard" / "demo_data"
        demo_dir.mkdir(parents=True)
        pd.DataFrame({"cpf": ["123"], "amount": [1.0]}).to_parquet(demo_dir / "t.parquet")
        check = _check_no_pii_like_columns_in_demo_data(tmp_path)
        assert check.status == "fail"
        assert "cpf" in check.detail

    def test_corrupt_parquet_is_skipped_not_crashed_on(self, tmp_path: Path) -> None:
        demo_dir = tmp_path / "dashboard" / "demo_data"
        demo_dir.mkdir(parents=True)
        (demo_dir / "corrupt.parquet").write_bytes(b"not actually parquet data")
        check = _check_no_pii_like_columns_in_demo_data(tmp_path)
        assert check.status == "pass"

    def test_pass_when_parquet_has_no_pii_like_column(self, tmp_path: Path) -> None:
        import pandas as pd

        demo_dir = tmp_path / "dashboard" / "demo_data"
        demo_dir.mkdir(parents=True)
        pd.DataFrame({"amount": [1.0]}).to_parquet(demo_dir / "t.parquet")
        check = _check_no_pii_like_columns_in_demo_data(tmp_path)
        assert check.status == "pass"


class TestCheckBilingualReportsPresent:
    def test_fail_when_reports_are_missing(self, tmp_path: Path) -> None:
        check = _check_bilingual_reports_present(tmp_path)
        assert check.status == "fail"
        assert "reports/modeling/model_card.md" in check.detail


class TestCheckModelArtifactsPresent:
    def test_fail_when_model_artifacts_missing(self, tmp_path: Path) -> None:
        check = _check_model_artifacts_present(tmp_path)
        assert check.status == "fail"


class TestCheckCiWorkflowNoMasking:
    def test_fail_when_workflow_file_missing(self, tmp_path: Path) -> None:
        check = _check_ci_workflow_no_masking(tmp_path)
        assert check.status == "fail"
        assert "No CI workflow" in check.detail

    def test_fail_when_masking_pattern_present_in_run_step(self, tmp_path: Path) -> None:
        workflow_dir = tmp_path / ".github" / "workflows"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "ci.yml").write_text(
            """
jobs:
  test:
    steps:
      - name: run tests
        run: pytest || true
""",
            encoding="utf-8",
        )
        check = _check_ci_workflow_no_masking(tmp_path)
        assert check.status == "fail"
        assert "|| true" in check.detail

    def test_pass_when_no_masking_pattern(self, tmp_path: Path) -> None:
        workflow_dir = tmp_path / ".github" / "workflows"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "ci.yml").write_text(
            """
jobs:
  test:
    steps:
      - name: run tests
        run: pytest
""",
            encoding="utf-8",
        )
        check = _check_ci_workflow_no_masking(tmp_path)
        assert check.status == "pass"


class TestReleaseValidateCliJsonOutput:
    def test_release_validate_json_flag_produces_valid_json(self) -> None:
        """Phase 10B section 16 - the CLI's `--json` output must itself be
        valid JSON, exercised end-to-end (never assumed from the human-
        readable branch alone)."""
        import io
        from contextlib import redirect_stdout

        from credlens.cli import main

        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["release", "validate", "--json"])
        payload = json.loads(buf.getvalue())
        assert "overall" in payload
        assert "checks" in payload
