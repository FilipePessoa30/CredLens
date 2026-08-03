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
from credlens.release.licenses import (
    DependencyLicense,
    LicenseInventory,
    _compatibility,
    _is_full_text_mit_license,
    _short_license,
    _spdx_compatibility,
    inventory_dependency_licenses,
)
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

    def test_phase10b_gates_are_present_in_the_report(self) -> None:
        """Phase 10B added coverage_gate/monitoring_detection_gate/
        direct_dependencies_have_licenses as REAL, evaluated checks -
        this is the regression test that would have caught RC1's own gap
        (a check simply not existing) had it existed at the time."""
        report = run_release_integrity_checks(Path.cwd())
        names = {c.name for c in report.checks}
        assert "coverage_gate" in names
        assert "monitoring_detection_gate" in names
        assert "direct_dependencies_have_licenses" in names


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

    @pytest.mark.slow
    def test_real_direct_dependencies_are_classified_separately_from_transitive(self) -> None:
        """Phase 10B section 15 - pandas/pyyaml/numpy (base runtime
        deps) must be classified `direct`; something deep in the
        dependency tree (e.g. a dbt-core sub-dependency never mentioned
        in pyproject.toml) must be classified `transitive`."""
        inventory = inventory_dependency_licenses(Path.cwd())
        assert inventory.direct_count > 0
        assert inventory.transitive_count > 0
        by_name = {d.name.lower(): d for d in inventory.dependencies}
        assert by_name["pyyaml"].dependency_kind == "direct"
        assert "runtime" in by_name["pyyaml"].roles

    @pytest.mark.slow
    def test_pep639_license_expression_is_read_for_modern_packages(self) -> None:
        """numpy 2.x/pydantic 2.x/scikit-learn ship ONLY a PEP 639
        `License-Expression` field, no legacy `License ::` classifier -
        an empirically-found real gap this project's original
        classifier-only check missed entirely (showed as "unknown")."""
        inventory = inventory_dependency_licenses(Path.cwd())
        by_name = {d.name.lower(): d for d in inventory.dependencies}
        for name in ("numpy", "pydantic"):
            if name in by_name:
                assert by_name[name].compatibility == "permissive_compatible", (
                    f"{name}: {by_name[name].license!r}"
                )

    @pytest.mark.slow
    def test_full_text_mit_license_field_packages_are_no_longer_unknown(self) -> None:
        """Fase 10C section 11 - kaleido (a DIRECT dependency, dashboard's
        optional PNG export) and its own transitive dependencies
        choreographer/logistro all ship the FULL MIT license text (not a
        short label) in the legacy `License` metadata field, defeating
        the short-single-line heuristic - verified against each
        package's own installed `licenses/LICENSE.md`/`LICENSE` file via
        `importlib.metadata`, never invented."""
        inventory = inventory_dependency_licenses(Path.cwd())
        by_name = {d.name.lower(): d for d in inventory.dependencies}
        for name in ("kaleido", "choreographer", "logistro"):
            if name in by_name:
                assert by_name[name].compatibility == "permissive_compatible", (
                    f"{name}: {by_name[name].license!r}"
                )
                assert by_name[name].license == "MIT License"

    def test_missing_pyproject_toml_treats_everything_as_transitive(self, tmp_path: Path) -> None:
        """`inventory_dependency_licenses` must not crash against an
        isolated fixture directory that has no pyproject.toml at all -
        it degrades to 'nothing is direct', never raises."""
        inventory = inventory_dependency_licenses(tmp_path)
        assert inventory.direct_count == 0
        assert all(d.dependency_kind == "transitive" for d in inventory.dependencies)

    def test_spdx_copyleft_expression_is_flagged(self) -> None:
        assert _spdx_compatibility("GPL-3.0-only") == "review_needed_copyleft"

    def test_spdx_mixed_permissive_expression_is_permissive(self) -> None:
        assert _spdx_compatibility("MIT AND BSD-3-Clause") == "permissive_compatible"

    def test_non_spdx_looking_label_returns_none(self) -> None:
        assert _spdx_compatibility("See LICENSE file for details") is None

    def test_direct_unknown_license_is_a_sharper_finding_than_transitive(self) -> None:
        assert _compatibility("unknown", is_direct=True) == "direct_unknown_license_needs_review"
        assert _compatibility("unknown", is_direct=False) == "unknown_review_needed"

    def test_license_inventory_direct_unknown_license_count_property(self) -> None:
        deps = [
            DependencyLicense(
                name="a",
                version="1",
                license="unknown",
                compatibility="direct_unknown_license_needs_review",
                dependency_kind="direct",
                roles=["runtime"],
            ),
            DependencyLicense(
                name="b",
                version="1",
                license="MIT",
                compatibility="permissive_compatible",
                dependency_kind="direct",
                roles=["runtime"],
            ),
        ]
        inventory = LicenseInventory(
            project_license="MIT",
            disclaimer_en="d",
            disclaimer_pt_br="d",
            dependencies=deps,
            unknown_count=1,
            copyleft_count=0,
        )
        assert inventory.direct_unknown_license_count == 1
        assert inventory.direct_count == 2
        assert inventory.transitive_count == 0
        assert "n_dependencies" in inventory.to_dict()


class _FakeDistributionMetadata:
    """Minimal stand-in for `importlib.metadata.PackageMetadata` - only
    the two accessors `_short_license` actually calls."""

    def __init__(
        self,
        *,
        license_expression: str | None = None,
        classifiers: list[str] | None = None,
        license_text: str | None = None,
    ) -> None:
        self._license_expression = license_expression
        self._classifiers = classifiers or []
        self._license_text = license_text

    def get(self, key: str, default: str | None = None) -> str | None:
        if key == "License-Expression":
            return self._license_expression
        if key == "License":
            return self._license_text
        return default

    def get_all(self, key: str, default: list[str] | None = None) -> list[str]:
        if key == "Classifier":
            return self._classifiers
        return default if default is not None else []


class TestShortLicenseFullTextMitFallback:
    """Fase 10C section 11 - the fallback that recognizes a FULL MIT
    license text dumped into the legacy `License` field (kaleido/
    choreographer/logistro's real, verified pattern), added alongside
    the pre-existing short-single-line heuristic, never replacing it."""

    def test_short_single_line_license_field_still_wins(self) -> None:
        metadata = _FakeDistributionMetadata(license_text="MIT")
        assert _short_license(metadata) == "MIT"

    def test_full_text_mit_license_field_is_recognized(self) -> None:
        metadata = _FakeDistributionMetadata(
            license_text=(
                "The MIT License (MIT)\n\nCopyright (c) Someone\n\n"
                "Permission is hereby granted, free of charge, to any person\n"
                "obtaining a copy of this software..."
            )
        )
        assert _short_license(metadata) == "MIT License"

    def test_full_text_non_mit_license_field_stays_unknown(self) -> None:
        # A long, multi-line License field that is NOT the MIT template -
        # proves the detector matches the MIT text itself, not "any long
        # License field".
        metadata = _FakeDistributionMetadata(
            license_text=(
                "Proprietary License\n\nAll rights reserved.\n\n"
                "No copying, modification, or redistribution is permitted\n"
                "without prior written consent of the copyright holder."
            )
        )
        assert _short_license(metadata) == "unknown"

    def test_is_full_text_mit_license_is_case_and_whitespace_insensitive(self) -> None:
        assert _is_full_text_mit_license(
            "PERMISSION IS   HEREBY\nGRANTED,\tFREE OF CHARGE, TO ANY PERSON"
        )

    def test_is_full_text_mit_license_false_for_unrelated_text(self) -> None:
        assert not _is_full_text_mit_license("Some other license entirely.")

    def test_dependency_to_dict_shape(self) -> None:
        dep = DependencyLicense(
            name="foo",
            version="1.0",
            license="MIT License",
            compatibility="permissive_compatible",
            dependency_kind="direct",
            roles=["runtime"],
        )
        assert dep.to_dict() == {
            "name": "foo",
            "version": "1.0",
            "license": "MIT License",
            "compatibility": "permissive_compatible",
            "dependency_kind": "direct",
            "roles": ["runtime"],
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

    def test_to_dict_shape(self) -> None:
        report = generate_sbom(Path.cwd())
        payload = report.to_dict()
        assert payload["bomFormat"] == "CycloneDX"
        assert payload["specVersion"] == report.spec_version
        assert payload["n_components"] == report.n_components
        assert payload["components"] == report.components

    def test_write_sbom_writes_a_real_json_file(self, tmp_path: Path) -> None:
        from credlens.release.sbom import write_sbom

        report = generate_sbom(Path.cwd())
        path = write_sbom(report, repo_root=tmp_path)
        assert path == tmp_path / "reports" / "release" / "sbom.cyclonedx.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["bomFormat"] == "CycloneDX"


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

    def test_missing_official_model_is_a_release_blocker(self, tmp_path: Path) -> None:
        """An isolated repo with no MODEL_behavioral_default_v1 at all
        must produce a real, visible blocker - never a silent
        `release_candidate_ready`."""
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

        manifest = build_release_manifest(
            test_counts={"total": 0},
            visual_qa_status="not_verified",
            docker_status="not_executed",
            ci_status="not_run_remotely_this_session",
            repo_root=tmp_path,
        )
        assert manifest.model_v1_present is False
        assert manifest.readiness_decision == "release_candidate_not_ready"
        assert any("MODEL_behavioral_default_v1" in b for b in manifest.release_blockers)

    def test_validation_failed_decision_is_a_release_blocker(self, tmp_path: Path) -> None:
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
        decision_dir = tmp_path / "reports" / "model_validation"
        decision_dir.mkdir(parents=True)
        (decision_dir / "decision.json").write_text(
            json.dumps({"decision": "validation_failed"}), encoding="utf-8"
        )
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

        manifest = build_release_manifest(
            test_counts={"total": 0},
            visual_qa_status="not_verified",
            docker_status="not_executed",
            ci_status="not_run_remotely_this_session",
            repo_root=tmp_path,
        )
        assert manifest.validation_decision == "validation_failed"
        assert any("validation_failed" in b for b in manifest.release_blockers)

    def test_write_release_manifest_writes_a_real_json_file(self, tmp_path: Path) -> None:
        from credlens.release.manifest import write_release_manifest

        manifest = build_release_manifest(
            test_counts={"total": 1500},
            visual_qa_status="verified_locally",
            docker_status="not_executed",
            ci_status="not_run_remotely_this_session",
            repo_root=Path.cwd(),
        )
        path = write_release_manifest(manifest, repo_root=tmp_path)
        assert path == tmp_path / "reports" / "release" / "release_manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["release_id"] == manifest.release_id


class TestReadJsonHelper:
    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        from credlens.release.manifest import _read_json

        assert _read_json(tmp_path / "nope.json") is None

    def test_returns_none_for_corrupt_json(self, tmp_path: Path) -> None:
        from credlens.release.manifest import _read_json

        path = tmp_path / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        assert _read_json(path) is None

    def test_returns_parsed_dict_for_valid_json(self, tmp_path: Path) -> None:
        from credlens.release.manifest import _read_json

        path = tmp_path / "good.json"
        path.write_text('{"a": 1}', encoding="utf-8")
        assert _read_json(path) == {"a": 1}


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
