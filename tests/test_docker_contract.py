"""Fase 13 - static contract checks for Dockerfile.dashboard/.dockerignore.

Pure text/AST-level assertions - no Docker daemon needed, so these run
in every environment (including CI matrix jobs with no Docker
available) as part of the normal fast test suite. The real
build-and-run checks (needs a live daemon) live in
tests/test_docker_integration.py, marked `docker`.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOCKERFILE = _REPO_ROOT / "Dockerfile.dashboard"
_DOCKERIGNORE = _REPO_ROOT / ".dockerignore"


def _dockerfile_text() -> str:
    return _DOCKERFILE.read_text(encoding="utf-8")


def _dockerignore_text() -> str:
    return _DOCKERIGNORE.read_text(encoding="utf-8")


class TestDockerfileExists:
    def test_dockerfile_and_dockerignore_are_present(self) -> None:
        assert _DOCKERFILE.is_file()
        assert _DOCKERIGNORE.is_file()


class TestBaseImage:
    def test_uses_an_official_versioned_python_slim_base_image(self) -> None:
        text = _dockerfile_text()
        assert "FROM python:3.11-slim" in text, (
            "base image must be an official, version-pinned python:*-slim tag"
        )
        # No `latest`/unpinned tag anywhere in a FROM line.
        for line in text.splitlines():
            if line.strip().upper().startswith("FROM"):
                assert ":latest" not in line


class TestNonRootUser:
    def test_creates_and_switches_to_a_non_root_user(self) -> None:
        text = _dockerfile_text()
        assert "useradd" in text
        assert "USER credlens" in text
        # USER must come after useradd, and nothing else switches back to root.
        useradd_pos = text.index("useradd")
        user_pos = text.index("USER credlens")
        assert useradd_pos < user_pos
        assert "USER root" not in text


class TestExposedPort:
    def test_exposes_only_the_streamlit_port(self) -> None:
        text = _dockerfile_text()
        expose_lines = [
            line.strip() for line in text.splitlines() if line.strip().startswith("EXPOSE")
        ]
        assert expose_lines == ["EXPOSE 8501"]


class TestHealthcheck:
    def test_has_a_healthcheck_hitting_the_streamlit_health_endpoint(self) -> None:
        text = _dockerfile_text()
        assert "HEALTHCHECK" in text
        assert "_stcore/health" in text
        assert "127.0.0.1" in text or "localhost" in text


class TestEntrypointAndCommand:
    def test_cmd_runs_streamlit_in_demo_mode(self) -> None:
        text = _dockerfile_text()
        assert 'CMD ["streamlit", "run"' in text
        assert "--demo" in text

    def test_cli_is_reachable_without_a_uv_run_prefix(self) -> None:
        text = _dockerfile_text()
        assert ".venv/bin" in text and "PATH" in text


class TestLockfileRespected:
    def test_uv_sync_uses_frozen_lockfile_and_skips_dev_deps(self) -> None:
        text = _dockerfile_text()
        assert "uv sync --frozen --no-dev" in text
        assert "COPY pyproject.toml uv.lock" in text


class TestNoForbiddenPatterns:
    def test_no_curl_pipe_shell(self) -> None:
        # Comment lines may legitimately mention "curl" (e.g. explaining it's
        # NOT needed) - only actual instruction lines matter here.
        instruction_lines = [
            line
            for line in _dockerfile_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        text = "\n".join(instruction_lines).lower()
        assert "curl" not in text, "no curl (and so no curl | bash) in the image build"
        assert "| bash" not in text and "| sh" not in text

    def test_no_hardcoded_secret_looking_assignments(self) -> None:
        text = _dockerfile_text().upper()
        for needle in ("PASSWORD=", "SECRET=", "API_KEY=", "TOKEN=", "PRIVATE_KEY"):
            assert needle not in text, f"suspicious secret-looking assignment found: {needle}"

    def test_no_add_instruction_from_a_remote_url(self) -> None:
        for line in _dockerfile_text().splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("ADD "):
                assert "http://" not in stripped and "https://" not in stripped

    def test_no_chmod_777_or_similarly_permissive_mode(self) -> None:
        text = _dockerfile_text()
        assert "777" not in text
        assert "chmod -R a+w" not in text


class TestDockerignoreExcludesSensitiveAndBulkyPaths:
    def test_excludes_vcs_and_local_env_state(self) -> None:
        text = _dockerignore_text()
        for needle in (".git/", ".venv/", "**/__pycache__/"):
            assert needle in text

    def test_excludes_test_and_report_directories(self) -> None:
        text = _dockerignore_text()
        for needle in ("tests/", "reports/", "notebooks/"):
            assert needle in text

    def test_excludes_the_gitignored_locally_generated_demo_bundle(self) -> None:
        text = _dockerignore_text()
        assert "dashboard/demo_data/" in text

    def test_excludes_gitignored_generated_warehouse_artifacts(self) -> None:
        text = _dockerignore_text()
        assert "warehouse/profiles.yml" in text
        assert "warehouse/.user.yml" in text
