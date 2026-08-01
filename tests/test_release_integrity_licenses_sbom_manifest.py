"""Tests for credlens.release (Phase 10 release-engineering layer):
integrity validator, license inventory, CycloneDX SBOM, and the
deterministic release manifest + readiness decision."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from credlens.release.integrity import (
    IntegrityCheck,
    ReleaseIntegrityReport,
    run_release_integrity_checks,
)
from credlens.release.licenses import DependencyLicense, inventory_dependency_licenses
from credlens.release.manifest import build_release_manifest, decide_readiness
from credlens.release.sbom import generate_sbom


class TestReleaseIntegrityReport:
    def test_pass_only_report_has_no_failure_or_warning(self) -> None:
        report = ReleaseIntegrityReport(
            checks=[IntegrityCheck("a", "pass", "ok"), IntegrityCheck("b", "pass", "ok")]
        )
        assert not report.has_failure
        assert not report.has_warning
        assert report.to_dict()["overall"] == "pass"

    def test_a_single_failure_makes_overall_fail(self) -> None:
        report = ReleaseIntegrityReport(
            checks=[IntegrityCheck("a", "pass", "ok"), IntegrityCheck("b", "fail", "bad")]
        )
        assert report.has_failure
        assert report.to_dict()["overall"] == "fail"

    def test_warning_without_failure_is_warning_overall(self) -> None:
        report = ReleaseIntegrityReport(
            checks=[IntegrityCheck("a", "pass", "ok"), IntegrityCheck("b", "warning", "meh")]
        )
        assert not report.has_failure
        assert report.has_warning
        assert report.to_dict()["overall"] == "warning"


@pytest.mark.slow
class TestRunReleaseIntegrityChecksOnRealRepo:
    def test_runs_without_raising_and_returns_every_check(self) -> None:
        report = run_release_integrity_checks(Path.cwd())
        names = {c.name for c in report.checks}
        assert "version_declared" in names
        assert "lockfile_present" in names
        assert "license_present" in names
        assert "no_secrets_in_tracked_files" in names
        assert "ci_workflow_no_masking" in names

    def test_ci_workflow_check_ignores_comments_discussing_the_pattern(self) -> None:
        # The real ci.yml has several comments that literally CONTAIN the
        # string "|| true" while explaining it was removed - the check
        # must parse `run:` step text, never a raw substring scan over
        # the whole file (which would false-positive on those comments).
        report = run_release_integrity_checks(Path.cwd())
        check = next(c for c in report.checks if c.name == "ci_workflow_no_masking")
        assert check.status == "pass"

    def test_official_model_artifacts_are_present(self) -> None:
        report = run_release_integrity_checks(Path.cwd())
        check = next(c for c in report.checks if c.name == "model_artifacts_present")
        assert check.status == "pass"


class TestLicenseInventory:
    def test_project_license_reads_the_license_file(self, tmp_path: Path) -> None:
        (tmp_path / "LICENSE").write_text("MIT License\n\nCopyright ...", encoding="utf-8")
        inventory = inventory_dependency_licenses(tmp_path)
        assert inventory.project_license == "MIT License"
        assert inventory.disclaimer_en == "Engineering license inventory - not legal advice."

    def test_missing_license_file_is_unknown(self, tmp_path: Path) -> None:
        inventory = inventory_dependency_licenses(tmp_path)
        assert inventory.project_license == "unknown"

    @pytest.mark.slow
    def test_real_environment_produces_many_dependency_rows(self) -> None:
        inventory = inventory_dependency_licenses(Path.cwd())
        assert len(inventory.dependencies) > 50
        assert inventory.unknown_count >= 0
        assert inventory.copyleft_count >= 0
        names = {d.name for d in inventory.dependencies}
        assert "pandas" in names or "scikit-learn" in names

    def test_dependency_to_dict_shape(self) -> None:
        dep = DependencyLicense(
            name="foo", version="1.0", license="MIT License", compatibility="permissive_compatible"
        )
        assert dep.to_dict() == {
            "name": "foo",
            "version": "1.0",
            "license": "MIT License",
            "compatibility": "permissive_compatible",
        }


@pytest.mark.slow
class TestGenerateSbom:
    def test_produces_cyclonedx_shaped_output(self) -> None:
        report = generate_sbom(Path.cwd())
        assert report.bom_format == "CycloneDX"
        assert report.serial_number.startswith("urn:uuid:")
        assert report.n_components == len(report.components)
        assert report.n_components > 50
        for component in report.components[:5]:
            assert component["type"] == "library"
            assert component["purl"].startswith("pkg:pypi/")

    def test_content_fingerprint_is_deterministic_across_runs(self) -> None:
        first = generate_sbom(Path.cwd())
        second = generate_sbom(Path.cwd())
        assert first.content_fingerprint == second.content_fingerprint
        # serialNumber is a fresh UUID every time (per the CycloneDX spec)
        assert first.serial_number != second.serial_number

    def test_disclaimer_present(self) -> None:
        report = generate_sbom(Path.cwd())
        assert "not" in report.disclaimer_en.lower()


class TestDecideReadiness:
    def test_any_blocker_is_not_ready(self) -> None:
        decision = decide_readiness(
            blockers=["something failed"],
            visual_qa_status="verified_locally",
            docker_status="built_and_validated",
        )
        assert decision == "release_candidate_not_ready"

    def test_no_blockers_but_visual_qa_not_verified_is_ready_with_limitations(self) -> None:
        decision = decide_readiness(
            blockers=[], visual_qa_status="not_verified", docker_status="built_and_validated"
        )
        assert decision == "release_candidate_ready_with_limitations"

    def test_no_blockers_but_docker_not_executed_is_ready_with_limitations(self) -> None:
        decision = decide_readiness(
            blockers=[], visual_qa_status="verified_locally", docker_status="not_executed"
        )
        assert decision == "release_candidate_ready_with_limitations"

    def test_no_blockers_and_both_fully_verified_is_fully_ready(self) -> None:
        decision = decide_readiness(
            blockers=[], visual_qa_status="verified_locally", docker_status="built_and_validated"
        )
        assert decision == "release_candidate_ready"

    def test_never_forced_to_ready_when_blockers_exist_even_if_verified(self) -> None:
        decision = decide_readiness(
            blockers=["x"], visual_qa_status="verified_locally", docker_status="built_and_validated"
        )
        assert decision != "release_candidate_ready"


@pytest.mark.slow
class TestBuildReleaseManifest:
    def test_produces_a_deterministic_content_fingerprint(self) -> None:
        first = build_release_manifest(
            test_counts={"total": 1500},
            visual_qa_status="verified_locally",
            docker_status="not_executed",
            ci_status="not_run_remotely_this_session",
            repo_root=Path.cwd(),
        )
        second = build_release_manifest(
            test_counts={"total": 1500},
            visual_qa_status="verified_locally",
            docker_status="not_executed",
            ci_status="not_run_remotely_this_session",
            repo_root=Path.cwd(),
        )
        assert first.content_fingerprint == second.content_fingerprint
        assert first.generated_at_utc != second.generated_at_utc

    def test_real_repo_reports_official_model_present(self) -> None:
        manifest = build_release_manifest(
            test_counts={"total": 1500},
            visual_qa_status="verified_locally",
            docker_status="not_executed",
            ci_status="not_run_remotely_this_session",
            repo_root=Path.cwd(),
        )
        assert manifest.model_v1_present is True
        assert manifest.base_commit
        assert manifest.readiness_decision in (
            "release_candidate_ready",
            "release_candidate_ready_with_limitations",
            "release_candidate_not_ready",
        )

    def test_known_limitations_are_disclosed_not_empty(self) -> None:
        manifest = build_release_manifest(
            test_counts={"total": 1500},
            visual_qa_status="verified_locally",
            docker_status="not_executed",
            ci_status="not_run_remotely_this_session",
            repo_root=Path.cwd(),
        )
        assert len(manifest.known_limitations) > 0
        joined = " ".join(manifest.known_limitations)
        assert "not suitable for real lending decisions" in joined.lower()


@pytest.mark.slow
class TestReleaseManifestRoundTrip:
    def test_to_dict_is_json_serializable(self) -> None:
        manifest = build_release_manifest(
            test_counts={"total": 1500},
            visual_qa_status="verified_locally",
            docker_status="not_executed",
            ci_status="not_run_remotely_this_session",
            repo_root=Path.cwd(),
        )
        # Raises if anything isn't JSON-serializable.
        json.dumps(manifest.to_dict())
