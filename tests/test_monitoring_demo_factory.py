"""Tests for credlens.demo.factory's monitoring component (Fase 11C Gate
B/D): the reference + simulated batches it (re)builds are exactly what
`credlens monitor evaluate-detection`/`evaluate-false-alerts` need,
gitignored and never committed. Runs against the real repo root (the
official, already-registered, already-frozen model, its config, and its
already-fetched UCI benchmark) - the same convention every other
monitoring integration test in this suite already uses; there is no
isolated-root variant of this pipeline to test against instead (Phase
9's own reference/batch machinery is inherently repo-root-coupled -
config, split assignment, and the raw benchmark all resolve relative to
it), so real end-to-end runs are unavoidable here, hence slow.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from credlens import __version__ as credlens_version
from credlens.demo.factory import (
    FACTORY_MANIFEST_SCHEMA_VERSION,
    MONITORING_GENERATOR_VERSION,
    DemoFactoryError,
    FactoryManifest,
    _existing_monitoring_bundle_is_complete_and_matching,
    prepare_monitoring_demo,
)

pytestmark = pytest.mark.slow

_MODEL_ID = "MODEL_behavioral_default_v1"
_REFERENCE_ID = f"REF_{_MODEL_ID}"
_REFERENCE_DIR = Path("reports/monitoring/reference")
_BATCH_DIR = Path("reports/monitoring/runs") / f"BATCHSET_{_REFERENCE_ID}"


@pytest.fixture(scope="module")
def prepared_reference() -> FactoryManifest:
    return prepare_monitoring_demo(model_id=_MODEL_ID, force=True, quiet=True)


class TestPreparation:
    def test_manifest_has_the_required_fields(self, prepared_reference: FactoryManifest) -> None:
        assert prepared_reference.schema_version >= 1
        assert prepared_reference.component == "monitoring"
        assert prepared_reference.generator_version
        assert prepared_reference.credlens_version
        assert prepared_reference.generated_at_utc
        assert prepared_reference.inputs["model_id"] == _MODEL_ID
        assert prepared_reference.outputs["reference_id"] == _REFERENCE_ID
        assert prepared_reference.outputs["batch_set_id"] == f"BATCHSET_{_REFERENCE_ID}"

    def test_all_expected_files_are_written(self, prepared_reference: FactoryManifest) -> None:
        assert (_REFERENCE_DIR / f"{_REFERENCE_ID}.json").is_file()
        assert (_REFERENCE_DIR / f"{_REFERENCE_ID}__population.csv").is_file()
        assert (_REFERENCE_DIR / f"{_REFERENCE_ID}__alert_thresholds.json").is_file()
        assert (_BATCH_DIR / "batch_manifest.json").is_file()
        assert (_BATCH_DIR / "batches").is_dir()
        assert any((_BATCH_DIR / "batches").glob("*.csv"))


class TestIdempotency:
    def test_second_call_without_force_is_a_no_op(
        self, prepared_reference: FactoryManifest
    ) -> None:
        ref_path = _REFERENCE_DIR / f"{_REFERENCE_ID}.json"
        mtime_before = ref_path.stat().st_mtime

        result = prepare_monitoring_demo(model_id=_MODEL_ID, force=False, quiet=True)

        assert ref_path.stat().st_mtime == mtime_before
        assert result.outputs["reference_id"] == _REFERENCE_ID

    def test_force_regenerates(self, prepared_reference: FactoryManifest) -> None:
        ref_path = _REFERENCE_DIR / f"{_REFERENCE_ID}.json"
        mtime_before = ref_path.stat().st_mtime

        prepare_monitoring_demo(model_id=_MODEL_ID, force=True, quiet=True)

        assert ref_path.stat().st_mtime >= mtime_before
        # Restore the module-scoped fixture's own state for later tests.
        prepare_monitoring_demo(model_id=_MODEL_ID, force=True, quiet=True)


class TestErrorHandling:
    def test_unknown_model_id_raises_an_actionable_error(self) -> None:
        with pytest.raises(DemoFactoryError):
            prepare_monitoring_demo(model_id="MODEL_this_does_not_exist_anywhere", force=True)


def _write_monitoring_factory_marker(
    repo_root: Path, *, model_id: str, generator_version: str = MONITORING_GENERATOR_VERSION
) -> None:
    reference_id = f"REF_{model_id}"
    marker_dir = repo_root / "reports" / "monitoring" / "reference"
    marker_dir.mkdir(parents=True, exist_ok=True)
    manifest = FactoryManifest(
        schema_version=FACTORY_MANIFEST_SCHEMA_VERSION,
        component="monitoring",
        generator_version=generator_version,
        seed=None,
        credlens_version=credlens_version,
        generated_at_utc="2026-01-01T00:00:00Z",
        inputs={"model_id": model_id},
        outputs={"reference_id": reference_id, "batch_set_id": f"BATCHSET_{reference_id}"},
    )
    (marker_dir / f"{reference_id}__factory_manifest.json").write_text(
        json.dumps(manifest.to_dict()), encoding="utf-8"
    )


class TestExistingBundleCheckBranches:
    """Direct, fast unit tests of the idempotency-check helper against a
    throwaway repo_root - the mismatch/corruption/incomplete cases a full
    reference+batch pipeline run would be a slow, indirect way to reach."""

    def test_returns_none_when_marker_is_absent(self, tmp_path: Path) -> None:
        assert _existing_monitoring_bundle_is_complete_and_matching(tmp_path, "MODEL_x") is None

    def test_returns_none_when_marker_is_corrupted(self, tmp_path: Path) -> None:
        marker_dir = tmp_path / "reports" / "monitoring" / "reference"
        marker_dir.mkdir(parents=True)
        (marker_dir / "REF_MODEL_x__factory_manifest.json").write_text(
            "{not valid json", encoding="utf-8"
        )
        assert _existing_monitoring_bundle_is_complete_and_matching(tmp_path, "MODEL_x") is None

    def test_returns_none_when_model_id_mismatches(self, tmp_path: Path) -> None:
        # Written at the SAME path a check for "MODEL_x" looks at (the
        # marker path is derived from the model_id being checked, not
        # from the marker's own content) - only the recorded
        # `inputs["model_id"]` disagrees, e.g. a copied/tampered marker.
        # A wrong model_id in the path itself is the "absent" case above.
        _write_monitoring_factory_marker(tmp_path, model_id="MODEL_x")
        marker_path = (
            tmp_path / "reports" / "monitoring" / "reference" / "REF_MODEL_x__factory_manifest.json"
        )
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
        payload["inputs"]["model_id"] = "MODEL_other"
        marker_path.write_text(json.dumps(payload), encoding="utf-8")

        assert _existing_monitoring_bundle_is_complete_and_matching(tmp_path, "MODEL_x") is None

    def test_returns_none_when_generator_version_mismatches(self, tmp_path: Path) -> None:
        _write_monitoring_factory_marker(
            tmp_path, model_id="MODEL_x", generator_version="0.0.0-old"
        )
        assert _existing_monitoring_bundle_is_complete_and_matching(tmp_path, "MODEL_x") is None

    def test_returns_none_when_a_required_file_is_missing(self, tmp_path: Path) -> None:
        _write_monitoring_factory_marker(tmp_path, model_id="MODEL_x")
        # No reference/batch files actually created next to the marker.
        assert _existing_monitoring_bundle_is_complete_and_matching(tmp_path, "MODEL_x") is None


class TestRaisesWithoutForceOnPreExistingState:
    def test_raises_when_incomplete_legacy_state_exists_without_force(self, tmp_path: Path) -> None:
        model_id = "MODEL_x"
        reference_dir = tmp_path / "reports" / "monitoring" / "reference"
        reference_dir.mkdir(parents=True)
        (reference_dir / f"REF_{model_id}.json").write_text("{}", encoding="utf-8")

        with pytest.raises(DemoFactoryError, match="already exists"):
            prepare_monitoring_demo(model_id=model_id, force=False, repo_root=tmp_path, quiet=True)


class TestDownstreamEvaluationWorks:
    """The real point of this factory (Fase 11B/11C's original finding):
    `evaluate-detection`/`evaluate-false-alerts` must actually succeed
    once the reference + batches it depends on have been (re)built -
    never assume a developer's machine already has them."""

    def test_evaluate_detection_succeeds_after_preparation(
        self, prepared_reference: FactoryManifest
    ) -> None:
        from credlens.monitoring.detection_eval import run_detection_evaluation

        report = run_detection_evaluation(_REFERENCE_ID)
        assert 0.0 <= report.scenario_detection_rate <= 1.0
        assert report.rows

    def test_evaluate_false_alerts_succeeds_after_preparation(
        self, prepared_reference: FactoryManifest
    ) -> None:
        from credlens.monitoring.reporting import false_alert_rate
        from credlens.monitoring.runner import run_monitoring

        # Reuses the batch set `prepared_reference` already simulated -
        # `simulate_batches` itself refuses to re-simulate into a
        # non-empty batches/ directory (by design, same as a warehouse
        # build's own --force semantics).
        batch_set_id = prepared_reference.outputs["batch_set_id"]
        run_id, _results, _alerts = run_monitoring(_REFERENCE_ID, batch_set_id)
        rate = false_alert_rate(run_id)
        assert 0.0 <= rate <= 1.0
