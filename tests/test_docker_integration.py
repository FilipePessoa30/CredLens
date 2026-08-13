"""Fase 13 - real, opt-in Docker build/run smoke tests against the actual
Dockerfile.dashboard image. Marked `docker` (see pyproject.toml) since
they need a live Docker daemon; deselect locally with `-m "not
docker"`. Absence of Docker is reported as an explicit, visible skip
reason - never a silent pass, and never treated as approval.

CI (see .github/workflows/ci.yml's `docker-build` job) runs these on
every PR with a real daemon; a Docker-less contributor environment
skips them loudly instead of failing.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOCKERFILE = _REPO_ROOT / "Dockerfile.dashboard"
_IMAGE_TAG = "credlens-dashboard-demo-test:ci"

pytestmark = pytest.mark.docker


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=10, check=False)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# A single, visible skip reason for the whole module - never a silent pass.
if not _docker_available():
    pytest.skip(
        "Docker daemon not reachable - Docker-dependent tests skipped explicitly "
        "(this is NOT equivalent to them passing).",
        allow_module_level=True,
    )


@pytest.fixture(scope="module")
def built_image() -> Iterator[str]:
    subprocess.run(
        ["docker", "build", "-f", str(_DOCKERFILE), "-t", _IMAGE_TAG, str(_REPO_ROOT)],
        check=True,
        timeout=900,
    )
    yield _IMAGE_TAG
    subprocess.run(["docker", "rmi", "-f", _IMAGE_TAG], check=False, timeout=60)


class TestImageBuilds:
    def test_image_builds_successfully(self, built_image: str) -> None:
        result = subprocess.run(
            ["docker", "image", "inspect", built_image],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0


class TestCliSmoke:
    def test_help_works_without_uv_run_prefix(self, built_image: str) -> None:
        result = subprocess.run(
            ["docker", "run", "--rm", built_image, "credlens", "--help"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        assert "CredLens" in result.stdout

    def test_version_reports_a_real_version(self, built_image: str) -> None:
        result = subprocess.run(
            ["docker", "run", "--rm", built_image, "credlens", "version"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        assert "credlens" in result.stdout.lower()


class TestContainerHealth:
    def test_container_becomes_healthy_and_serves_http(self, built_image: str) -> None:
        container_name = f"credlens-ci-health-{uuid.uuid4().hex[:8]}"
        subprocess.run(
            ["docker", "run", "-d", "--name", container_name, built_image],
            check=True,
            capture_output=True,
            timeout=30,
        )
        try:
            status = "starting"
            for _ in range(30):
                inspect = subprocess.run(
                    [
                        "docker",
                        "inspect",
                        "--format={{.State.Health.Status}}",
                        container_name,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                status = inspect.stdout.strip()
                if status == "healthy":
                    break
                time.sleep(4)
            assert status == "healthy", f"container did not become healthy (last status={status})"

            logs = subprocess.run(
                ["docker", "logs", container_name], capture_output=True, text=True, timeout=10
            )
            assert "Traceback (most recent call last)" not in logs.stdout
            assert "Traceback (most recent call last)" not in logs.stderr
        finally:
            subprocess.run(["docker", "rm", "-f", container_name], check=False, timeout=30)

    def test_demo_bundle_loads_inside_the_container(self, built_image: str) -> None:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                built_image,
                "python",
                "-c",
                (
                    "from credlens.dashboard.bootstrap import load_validated_dashboard_data\n"
                    "config, data = load_validated_dashboard_data()\n"
                    "assert data.mode == 'demo'\n"
                    "assert len(data.tables) > 0\n"
                    "print('OK', data.fingerprint)\n"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "OK" in result.stdout
