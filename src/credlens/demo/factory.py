"""Fase 11C Gate B - deterministic demo-data factory.

Orchestrates the EXISTING pipelines end to end - never a second,
parallel implementation:

  dashboard: credlens.generation.suite.generate_suite
             -> credlens.warehouse.build.run_build
             -> credlens.analysis.runner.run_analysis
             -> credlens.dashboard.demo_package.build_demo_package

  monitoring: credlens.monitoring.reporting.create_reference
              -> credlens.monitoring.reporting.calibrate_reference_family_wise
              -> credlens.monitoring.reporting.simulate_batches

Both components are fully reproducible from a seed (dashboard) or the
already-committed official model (monitoring) - neither depends on any
locally-generated file already sitting on disk. Outputs are written
atomically (staged in a temp directory, then swapped into place) and
are idempotent: calling `prepare_*` again with the same inputs and an
already-complete, matching output is a no-op unless `force=True`.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from credlens import __version__ as credlens_version

FACTORY_MANIFEST_SCHEMA_VERSION = 1

# Bumped only when the GENERATION algorithm itself changes in a way
# that would produce different output for the same seed/inputs -
# tracked separately from `credlens_version` (which changes on every
# release regardless of whether this factory's own logic changed).
DASHBOARD_GENERATOR_VERSION = "1.0.0"
MONITORING_GENERATOR_VERSION = "1.0.0"

DASHBOARD_SCALE = "smoke"
DEFAULT_MODEL_ID = "MODEL_behavioral_default_v1"
DEFAULT_DASHBOARD_SEED = 42

FACTORY_MANIFEST_FILENAME = "demo_factory_manifest.json"

Component = Literal["dashboard", "monitoring"]


class DemoFactoryError(Exception):
    """Raised when a demo-data component cannot be prepared."""


@dataclass(frozen=True)
class FactoryManifest:
    schema_version: int
    component: str
    generator_version: str
    seed: int | None
    credlens_version: str
    generated_at_utc: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "component": self.component,
            "generator_version": self.generator_version,
            "seed": self.seed,
            "credlens_version": self.credlens_version,
            "generated_at_utc": self.generated_at_utc,
            "inputs": self.inputs,
            "outputs": self.outputs,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> FactoryManifest:
        return FactoryManifest(
            schema_version=raw["schema_version"],
            component=raw["component"],
            generator_version=raw["generator_version"],
            seed=raw.get("seed"),
            credlens_version=raw["credlens_version"],
            generated_at_utc=raw["generated_at_utc"],
            inputs=raw["inputs"],
            outputs=raw["outputs"],
        )


def _write_factory_manifest(output_dir: Path, manifest: FactoryManifest) -> Path:
    """Written LAST, after every other artifact is already on disk - its
    mere presence is this factory's own "generation completed" marker,
    used by the idempotency/completeness check on the next call."""
    path = output_dir / FACTORY_MANIFEST_FILENAME
    path.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def _load_factory_manifest(output_dir: Path) -> FactoryManifest | None:
    path = output_dir / FACTORY_MANIFEST_FILENAME
    if not path.is_file():
        return None
    try:
        return FactoryManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, KeyError):
        return None


def _atomic_replace_dir(staging_dir: Path, final_dir: Path) -> None:
    """Swaps `staging_dir` into `final_dir`'s place. Refuses to touch
    `final_dir` at all unless it is either absent, empty, or already
    carries this factory's own completion marker (`FACTORY_MANIFEST_
    FILENAME`) - proving a PRIOR run of this exact factory owns it,
    never an arbitrary directory a caller happened to point --output
    at. Never a recursive delete of unrecognized content."""
    if final_dir.exists():
        is_empty = not any(final_dir.iterdir())
        is_factory_owned = (final_dir / FACTORY_MANIFEST_FILENAME).is_file()
        if not (is_empty or is_factory_owned):
            raise DemoFactoryError(
                f"Refusing to overwrite '{final_dir}' - it exists, is non-empty, and does not "
                f"carry this factory's own '{FACTORY_MANIFEST_FILENAME}' marker. Point --output "
                "at an empty or factory-owned directory."
            )
        shutil.rmtree(final_dir)
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging_dir), str(final_dir))


def _existing_dashboard_bundle_is_complete_and_matching(
    output_dir: Path, seed: int
) -> FactoryManifest | None:
    from credlens.dashboard.demo_package import DemoPackageError, validate_demo_package

    factory_manifest = _load_factory_manifest(output_dir)
    if factory_manifest is None:
        return None
    if factory_manifest.component != "dashboard" or factory_manifest.seed != seed:
        return None
    if factory_manifest.generator_version != DASHBOARD_GENERATOR_VERSION:
        return None
    try:
        validate_demo_package(output_dir)
    except DemoPackageError:
        return None
    return factory_manifest


def prepare_dashboard_demo(
    *, seed: int, output_dir: Path, force: bool = False, quiet: bool = False
) -> FactoryManifest:
    """Deterministically produces the dashboard's demo Parquet bundle
    (the same shape `credlens dashboard export-demo` writes) at
    `output_dir`, entirely from `seed` - no pre-existing local artifact
    required. Idempotent: an already-complete bundle for the same seed
    is left untouched unless `force=True`."""

    def _log(msg: str) -> None:
        if not quiet:
            print(f"[demo prepare/dashboard] {msg}")

    if not force:
        existing = _existing_dashboard_bundle_is_complete_and_matching(output_dir, seed)
        if existing is not None:
            _log(f"'{output_dir}' already has a matching bundle (seed={seed}) - skipping.")
            return existing

    from credlens.analysis.runner import run_analysis
    from credlens.dashboard.demo_package import build_demo_package
    from credlens.generation.suite import generate_suite
    from credlens.warehouse.build import _rmtree_with_retry, build_dir_for, run_build

    build_id = f"BUILD_demo_prepare_{seed}"
    # A seed-derived, STABLE staging path - never `tempfile.
    # TemporaryDirectory()` (a fresh random path every call). Confirmed
    # by direct reproduction: `operational_dir`/`truth_dir` are part of
    # `canonical_config_hash`'s own payload (Phase 6 gate B, by design -
    # see `credlens.generation.config.with_output_dirs`'s docstring), so
    # a random staging path made every `generation_run_id` (and every
    # row's `run_id` column) different across two calls with the
    # IDENTICAL seed, breaking determinism. Removed at the end either
    # way (success or failure) - this is scratch/intermediate, never the
    # final bundle.
    tmp_path = Path(tempfile.gettempdir()) / "credlens_demo_factory" / f"dashboard_seed_{seed}"
    if tmp_path.exists():
        # Fase 11D - a prior invocation's DuckDB/dbt connection over a
        # *.duckdb file under this same tmp_path can still be releasing
        # its OS-level file handle asynchronously (see `_rmtree_with_
        # retry`'s own docstring) when this next call starts - confirmed
        # by direct reproduction on Windows (PermissionError/WinError32
        # deleting a sibling *.parquet mid-rmtree, immediately after a
        # previous call to this same seed's staging path).
        _rmtree_with_retry(tmp_path)
    tmp_path.mkdir(parents=True)
    try:
        operational_dir = tmp_path / "operational"
        truth_dir = tmp_path / "truth"
        manifest_dir = tmp_path / "manifests"
        analysis_dir = tmp_path / "analysis"

        _log(f"generating a '{DASHBOARD_SCALE}'-scale synthetic suite (seed={seed})...")
        outcome = generate_suite(
            scale_name=DASHBOARD_SCALE,
            seed=seed,
            force=True,
            output_dirs=(operational_dir, truth_dir),
            manifest_dir=manifest_dir,
        )

        _log(f"building the warehouse (build_id={build_id})...")
        build_manifest = None
        try:
            build_manifest = run_build(
                suite_id=outcome.suite_id,
                build_id=build_id,
                force=True,
                operational_root=operational_dir,
                manifest_dir=manifest_dir,
                quiet=quiet,
            )
            if build_manifest.final_status != "success":
                raise DemoFactoryError(
                    f"Warehouse build '{build_id}' did not succeed "
                    f"(final_status={build_manifest.final_status!r})."
                )

            _log("running the portfolio analysis layer...")
            # include_benchmark=False: the benchmark appendix needs the
            # real, already-acquired public sources (UCI/BCB) on disk,
            # which this factory never assumes are present - the demo
            # bundle's own Public Benchmarks page degrades gracefully
            # without it (see credlens.analysis.benchmark.
            # profile_public_sources). include_insights=True: matches
            # the shape of the existing dashboard/demo_data/ package
            # (which ships an insights.yml).
            run_analysis(
                build_id=build_id,
                output_dir=analysis_dir,
                include_benchmark=False,
                include_insights=True,
            )

            staging_dir = tmp_path / "demo_staging"
            _log("packaging the demo bundle (aggregate tables only)...")
            demo_manifest = build_demo_package(
                analysis_output_dir=analysis_dir,
                output_dir=staging_dir,
                db_path=Path(build_manifest.db_path),
                suite_id=outcome.suite_id,
            )

            factory_manifest = FactoryManifest(
                schema_version=FACTORY_MANIFEST_SCHEMA_VERSION,
                component="dashboard",
                generator_version=DASHBOARD_GENERATOR_VERSION,
                seed=seed,
                credlens_version=credlens_version,
                generated_at_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                inputs={
                    "scale": DASHBOARD_SCALE,
                    "suite_id": outcome.suite_id,
                    "build_id": build_id,
                },
                outputs={
                    "tables": {
                        name: {"row_count": t.row_count, "sha256": t.sha256}
                        for name, t in demo_manifest.tables.items()
                    },
                    "total_size_bytes": demo_manifest.total_size_bytes,
                    "insights_included": demo_manifest.insights_included,
                },
            )
            _write_factory_manifest(staging_dir, factory_manifest)

            _log(f"writing the final bundle to '{output_dir}'...")
            _atomic_replace_dir(staging_dir, output_dir)
        finally:
            build_dir = build_dir_for(build_id)
            if build_dir.exists():
                try:
                    _rmtree_with_retry(build_dir)
                except PermissionError:
                    shutil.rmtree(build_dir, ignore_errors=True)
    finally:
        try:
            _rmtree_with_retry(tmp_path)
        except PermissionError:
            shutil.rmtree(tmp_path, ignore_errors=True)

    _log("done.")
    return factory_manifest


def _existing_monitoring_bundle_is_complete_and_matching(
    repo_root: Path, model_id: str
) -> FactoryManifest | None:
    reference_id = f"REF_{model_id}"
    marker_path = (
        repo_root
        / "reports"
        / "monitoring"
        / "reference"
        / (f"{reference_id}__factory_manifest.json")
    )
    if not marker_path.is_file():
        return None
    try:
        factory_manifest = FactoryManifest.from_dict(
            json.loads(marker_path.read_text(encoding="utf-8"))
        )
    except (json.JSONDecodeError, KeyError):
        return None
    if factory_manifest.component != "monitoring" or factory_manifest.inputs.get("model_id") != (
        model_id
    ):
        return None
    if factory_manifest.generator_version != MONITORING_GENERATOR_VERSION:
        return None
    required = [
        repo_root / "reports" / "monitoring" / "reference" / f"{reference_id}.json",
        repo_root / "reports" / "monitoring" / "reference" / f"{reference_id}__population.csv",
        repo_root
        / "reports"
        / "monitoring"
        / "reference"
        / f"{reference_id}__alert_thresholds.json",
        repo_root
        / "reports"
        / "monitoring"
        / "runs"
        / f"BATCHSET_{reference_id}"
        / "batch_manifest.json",
    ]
    if not all(p.is_file() for p in required):
        return None
    return factory_manifest


def prepare_monitoring_demo(
    *,
    model_id: str = DEFAULT_MODEL_ID,
    force: bool = False,
    repo_root: Path | None = None,
    quiet: bool = False,
) -> FactoryManifest:
    """Deterministically (re)builds the monitoring reference + simulated
    batches for `model_id` - the exact artifacts `credlens monitor
    evaluate-detection`/`evaluate-false-alerts` need, which are
    gitignored and never committed. Reuses the existing monitor
    create-reference/calibrate-reference/simulate-batches pipeline
    verbatim; tightly coupled to `repo_root` by that pipeline's own
    design (it reads the registered model, target contract, and split
    assignment from repo-relative paths), so - unlike the dashboard
    component - this does not support an arbitrary external --output;
    it always (re)writes the existing reports/monitoring/ locations,
    already covered by .gitignore."""

    def _log(msg: str) -> None:
        if not quiet:
            print(f"[demo prepare/monitoring] {msg}")

    repo_root = repo_root or Path.cwd()
    reference_id = f"REF_{model_id}"
    batch_set_id = f"BATCHSET_{reference_id}"
    reference_dir = repo_root / "reports" / "monitoring" / "reference"
    batch_dir = repo_root / "reports" / "monitoring" / "runs" / batch_set_id

    if not force:
        existing = _existing_monitoring_bundle_is_complete_and_matching(repo_root, model_id)
        if existing is not None:
            _log(f"a matching reference+batches already exists for '{model_id}' - skipping.")
            return existing

    ref_json = reference_dir / f"{reference_id}.json"
    ref_population = reference_dir / f"{reference_id}__population.csv"
    ref_thresholds = reference_dir / f"{reference_id}__alert_thresholds.json"
    ref_factory_marker = reference_dir / f"{reference_id}__factory_manifest.json"
    already_present = ref_json.is_file() or batch_dir.is_dir()
    if already_present and not force:
        raise DemoFactoryError(
            f"A reference and/or batch set already exists for '{model_id}' "
            f"(reference_id='{reference_id}') but is incomplete or from a different "
            "generator version - pass force=True (CLI: --force) to regenerate it."
        )
    if already_present and force:
        _log(f"removing the existing, factory-owned reference/batches for '{model_id}'...")
        for path in (ref_json, ref_population, ref_thresholds, ref_factory_marker):
            path.unlink(missing_ok=True)
        if batch_dir.is_dir():
            shutil.rmtree(batch_dir)

    from credlens.monitoring.reporting import (
        calibrate_reference_family_wise,
        create_reference,
        simulate_batches,
    )

    try:
        _log(f"creating the monitoring reference for '{model_id}'...")
        created_reference_id = create_reference(model_id, repo_root=repo_root)

        _log("calibrating family-wise PSI thresholds...")
        calibrate_reference_family_wise(created_reference_id, repo_root=repo_root)

        _log("simulating the batch set (drift/data-quality/label-delay scenarios)...")
        created_batch_set_id = simulate_batches(created_reference_id, repo_root=repo_root)
    except Exception as exc:
        # A single, predictable exception type for every way preparation
        # can fail (an unregistered model_id, a missing UCI fetch, a
        # missing split assignment, ...) - never a caller-unfriendly mix
        # of RegistryError/ReferenceError/DataAcquisitionError/SplitError
        # from deep inside the pipeline this reuses.
        raise DemoFactoryError(
            f"Could not prepare the monitoring reference for '{model_id}': {exc}"
        ) from exc

    factory_manifest = FactoryManifest(
        schema_version=FACTORY_MANIFEST_SCHEMA_VERSION,
        component="monitoring",
        generator_version=MONITORING_GENERATOR_VERSION,
        seed=None,  # deterministic from the already-frozen registered model - no seed of its own
        credlens_version=credlens_version,
        generated_at_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        inputs={"model_id": model_id},
        outputs={"reference_id": created_reference_id, "batch_set_id": created_batch_set_id},
    )
    ref_factory_marker.write_text(
        json.dumps(factory_manifest.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
    )
    _log("done.")
    return factory_manifest
