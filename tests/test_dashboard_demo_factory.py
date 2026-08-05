"""Tests for credlens.demo.factory's dashboard component (Fase 11C Gate
B/C): determinism, idempotency, custom output directories, --force
safety, manifest/hash content, and the dashboard's own auto-generation
on first use. Real end-to-end runs (generation -> warehouse -> analysis
-> demo package), so these are slow.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from credlens import __version__ as credlens_version
from credlens.dashboard.demo_package import validate_demo_package
from credlens.demo.factory import (
    DASHBOARD_GENERATOR_VERSION,
    FACTORY_MANIFEST_SCHEMA_VERSION,
    DemoFactoryError,
    FactoryManifest,
    _existing_dashboard_bundle_is_complete_and_matching,
    _load_factory_manifest,
    prepare_dashboard_demo,
)

pytestmark = pytest.mark.slow

_SEED_A = 910_001
_SEED_B = 910_002


@pytest.fixture(scope="module")
def bundle_a(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, FactoryManifest]:
    out = tmp_path_factory.mktemp("demo_factory_a") / "bundle"
    manifest = prepare_dashboard_demo(seed=_SEED_A, output_dir=out, force=True, quiet=True)
    return out, manifest


class TestDeterminism:
    def test_two_independent_runs_with_the_same_seed_hash_identically(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        out1 = tmp_path_factory.mktemp("demo_factory_det1") / "bundle"
        out2 = tmp_path_factory.mktemp("demo_factory_det2") / "bundle"
        m1 = prepare_dashboard_demo(seed=_SEED_A, output_dir=out1, force=True, quiet=True)
        m2 = prepare_dashboard_demo(seed=_SEED_A, output_dir=out2, force=True, quiet=True)

        h1 = {name: t["sha256"] for name, t in m1.outputs["tables"].items()}
        h2 = {name: t["sha256"] for name, t in m2.outputs["tables"].items()}
        assert h1 == h2

    def test_different_seeds_produce_different_content(
        self, bundle_a: tuple[Path, FactoryManifest], tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        _out_a, manifest_a = bundle_a
        out_b = tmp_path_factory.mktemp("demo_factory_b") / "bundle"
        manifest_b = prepare_dashboard_demo(seed=_SEED_B, output_dir=out_b, force=True, quiet=True)

        h_a = {name: t["sha256"] for name, t in manifest_a.outputs["tables"].items()}
        h_b = {name: t["sha256"] for name, t in manifest_b.outputs["tables"].items()}
        assert h_a != h_b

    def test_generated_at_timestamp_does_not_leak_into_table_hashes(
        self, bundle_a: tuple[Path, FactoryManifest], tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Two runs a moment apart (different wall-clock `generated_at_
        utc`) must still hash identically - no volatile timestamp
        reaches the actual table content."""
        _out_a, manifest_a = bundle_a
        out_again = tmp_path_factory.mktemp("demo_factory_a_again") / "bundle"
        manifest_again = prepare_dashboard_demo(
            seed=_SEED_A, output_dir=out_again, force=True, quiet=True
        )
        assert manifest_a.generated_at_utc != manifest_again.generated_at_utc
        h_a = {name: t["sha256"] for name, t in manifest_a.outputs["tables"].items()}
        h_again = {name: t["sha256"] for name, t in manifest_again.outputs["tables"].items()}
        assert h_a == h_again


class TestIdempotency:
    def test_second_call_without_force_is_a_no_op(
        self, bundle_a: tuple[Path, FactoryManifest]
    ) -> None:
        out, _manifest = bundle_a
        manifest_path = out / "manifest.json"
        mtime_before = manifest_path.stat().st_mtime

        result = prepare_dashboard_demo(seed=_SEED_A, output_dir=out, force=False, quiet=True)

        assert manifest_path.stat().st_mtime == mtime_before
        assert result.seed == _SEED_A

    def test_force_regenerates_even_when_already_complete(
        self, bundle_a: tuple[Path, FactoryManifest]
    ) -> None:
        out, _manifest = bundle_a
        manifest_path = out / "manifest.json"
        mtime_before = manifest_path.stat().st_mtime

        prepare_dashboard_demo(seed=_SEED_A, output_dir=out, force=True, quiet=True)

        assert manifest_path.stat().st_mtime >= mtime_before


class TestCustomOutputDirectory:
    def test_writes_to_the_exact_directory_requested(
        self, bundle_a: tuple[Path, FactoryManifest]
    ) -> None:
        out, _manifest = bundle_a
        assert (out / "manifest.json").is_file()
        assert (out / "demo_factory_manifest.json").is_file()
        assert any(out.glob("*.parquet"))


class TestForceSafety:
    def test_refuses_to_overwrite_a_non_empty_unrecognized_directory(self, tmp_path: Path) -> None:
        foreign_dir = tmp_path / "foreign"
        foreign_dir.mkdir()
        (foreign_dir / "unrelated_file.txt").write_text("do not touch me", encoding="utf-8")

        with pytest.raises(DemoFactoryError, match="Refusing to overwrite"):
            prepare_dashboard_demo(seed=_SEED_A, output_dir=foreign_dir, force=True, quiet=True)

        # The unrelated file must survive untouched.
        assert (foreign_dir / "unrelated_file.txt").read_text(encoding="utf-8") == (
            "do not touch me"
        )

    def test_accepts_an_empty_pre_existing_directory(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "already_here_but_empty"
        empty_dir.mkdir()
        manifest = prepare_dashboard_demo(
            seed=_SEED_A, output_dir=empty_dir, force=True, quiet=True
        )
        assert manifest.component == "dashboard"


class TestManifestAndHashes:
    def test_factory_manifest_has_the_required_fields(
        self, bundle_a: tuple[Path, FactoryManifest]
    ) -> None:
        _out, manifest = bundle_a
        assert manifest.schema_version >= 1
        assert manifest.component == "dashboard"
        assert manifest.generator_version
        assert manifest.seed == _SEED_A
        assert manifest.credlens_version
        assert manifest.generated_at_utc
        assert "suite_id" in manifest.inputs
        assert "build_id" in manifest.inputs
        assert manifest.outputs["tables"]
        for table in manifest.outputs["tables"].values():
            assert table["row_count"] >= 0
            assert len(table["sha256"]) == 64

    def test_demo_package_validates_via_the_dashboards_own_tamper_check(
        self, bundle_a: tuple[Path, FactoryManifest]
    ) -> None:
        out, _manifest = bundle_a
        validated = validate_demo_package(out)
        assert len(validated.tables) == len(_manifest_tables(bundle_a))


def _manifest_tables(bundle: tuple[Path, FactoryManifest]) -> dict[str, object]:
    _out, manifest = bundle
    tables: dict[str, object] = manifest.outputs["tables"]
    return tables


class TestSchema:
    """At least the 8 pages' worth of tables the dashboard reads must be
    present - see dashboard/README.md's page/table dictionary."""

    _REQUIRED_TABLES = (
        "funnel_monthly",
        "portfolio_monthly",
        "delinquency_monthly",
        "vintage_cohorts",
        "roll_rates",
        "collections_performance",
        "writeoff_recovery",
        "scenario_comparison",
    )

    def test_every_required_table_is_present(self, bundle_a: tuple[Path, FactoryManifest]) -> None:
        _out, manifest = bundle_a
        present = set(manifest.outputs["tables"].keys())
        missing = [t for t in self._REQUIRED_TABLES if t not in present]
        assert missing == [], f"missing required demo table(s): {missing}"

    def test_no_forbidden_identifying_column_in_any_table(
        self, bundle_a: tuple[Path, FactoryManifest]
    ) -> None:
        import pandas as pd

        out, manifest = bundle_a
        forbidden = {"contract_key", "contract_id", "customer_key", "customer_id"}
        for name in manifest.outputs["tables"]:
            columns = set(pd.read_parquet(out / f"{name}.parquet").columns)
            assert not (forbidden & columns), f"{name} carries forbidden column(s)"


class TestDashboardAutoGeneration:
    def test_dashboard_demo_mode_generates_a_bundle_on_first_use(self, tmp_path: Path) -> None:
        from credlens.dashboard.bootstrap import load_validated_dashboard_data

        demo_dir = tmp_path / "auto_generated_demo"
        assert not demo_dir.exists()

        config, data = load_validated_dashboard_data(["--demo", "--demo-data-dir", str(demo_dir)])

        assert config.mode == "demo"
        assert (demo_dir / "manifest.json").is_file()
        assert len(data.tables) > 0

    def test_second_page_load_does_not_regenerate(self, tmp_path: Path) -> None:
        from credlens.dashboard.bootstrap import load_validated_dashboard_data

        demo_dir = tmp_path / "auto_generated_demo_2"
        load_validated_dashboard_data(["--demo", "--demo-data-dir", str(demo_dir)])
        mtime_before = (demo_dir / "manifest.json").stat().st_mtime

        load_validated_dashboard_data(["--demo", "--demo-data-dir", str(demo_dir)])

        assert (demo_dir / "manifest.json").stat().st_mtime == mtime_before

    def test_warehouse_mode_never_falls_back_to_synthetic_data(self, tmp_path: Path) -> None:
        """--build-id mode must fail loudly on a nonexistent build, never
        silently substitute demo/synthetic data."""
        from credlens.dashboard.bootstrap import BootstrapError, load_validated_dashboard_data

        with pytest.raises(BootstrapError):
            load_validated_dashboard_data(["--build-id", "BUILD_this_does_not_exist_anywhere"])


def _write_dashboard_factory_manifest(
    output_dir: Path, *, seed: int, generator_version: str = DASHBOARD_GENERATOR_VERSION
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = FactoryManifest(
        schema_version=FACTORY_MANIFEST_SCHEMA_VERSION,
        component="dashboard",
        generator_version=generator_version,
        seed=seed,
        credlens_version=credlens_version,
        generated_at_utc="2026-01-01T00:00:00Z",
        inputs={},
        outputs={},
    )
    (output_dir / "demo_factory_manifest.json").write_text(
        json.dumps(manifest.to_dict()), encoding="utf-8"
    )


class TestExistingBundleCheckBranches:
    """Direct, fast unit tests of the idempotency-check helpers - the
    mismatch/corruption cases a full generation-pipeline run would be a
    slow, indirect way to exercise."""

    def test_load_factory_manifest_returns_none_when_absent(self, tmp_path: Path) -> None:
        assert _load_factory_manifest(tmp_path) is None

    def test_load_factory_manifest_returns_none_when_corrupted(self, tmp_path: Path) -> None:
        (tmp_path / "demo_factory_manifest.json").write_text("{not valid json", encoding="utf-8")
        assert _load_factory_manifest(tmp_path) is None

    def test_existing_bundle_is_none_when_no_manifest(self, tmp_path: Path) -> None:
        assert _existing_dashboard_bundle_is_complete_and_matching(tmp_path, seed=1) is None

    def test_existing_bundle_is_none_when_seed_mismatches(self, tmp_path: Path) -> None:
        _write_dashboard_factory_manifest(tmp_path, seed=1)
        assert _existing_dashboard_bundle_is_complete_and_matching(tmp_path, seed=2) is None

    def test_existing_bundle_is_none_when_generator_version_mismatches(
        self, tmp_path: Path
    ) -> None:
        _write_dashboard_factory_manifest(tmp_path, seed=1, generator_version="0.0.0-old")
        assert _existing_dashboard_bundle_is_complete_and_matching(tmp_path, seed=1) is None

    def test_existing_bundle_is_none_when_validation_fails(self, tmp_path: Path) -> None:
        # A matching manifest but none of the actual bundle content beside
        # it - `validate_demo_package` must reject it as incomplete.
        _write_dashboard_factory_manifest(tmp_path, seed=1)
        assert _existing_dashboard_bundle_is_complete_and_matching(tmp_path, seed=1) is None


class TestLoggingAndStaleStateHandling:
    def test_verbose_logging_prints_progress(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        prepare_dashboard_demo(seed=_SEED_A, output_dir=tmp_path / "bundle", force=True)
        captured = capsys.readouterr()
        assert "[demo prepare/dashboard]" in captured.out

    def test_stale_staging_directory_from_an_interrupted_run_is_cleaned_up(
        self, tmp_path: Path
    ) -> None:
        import tempfile

        seed = 910_099
        stale = Path(tempfile.gettempdir()) / "credlens_demo_factory" / f"dashboard_seed_{seed}"
        stale.mkdir(parents=True, exist_ok=True)
        (stale / "leftover_from_a_killed_run.txt").write_text("stale", encoding="utf-8")

        manifest = prepare_dashboard_demo(
            seed=seed, output_dir=tmp_path / "bundle", force=True, quiet=True
        )

        assert manifest.seed == seed
        assert not stale.exists()

    def test_raises_when_the_warehouse_build_does_not_succeed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import types

        import credlens.warehouse.build as warehouse_build_module

        def _fake_run_build(**_kwargs: object) -> types.SimpleNamespace:
            return types.SimpleNamespace(final_status="failed", db_path="unused.duckdb")

        monkeypatch.setattr(warehouse_build_module, "run_build", _fake_run_build)

        with pytest.raises(DemoFactoryError, match="did not succeed"):
            prepare_dashboard_demo(
                seed=910_098, output_dir=tmp_path / "bundle", force=True, quiet=True
            )


class TestCliCollectsCleanly:
    def test_demo_prepare_is_registered_on_the_cli(self) -> None:
        from credlens.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            ["demo", "prepare", "--component", "dashboard", "--seed", "1", "--force"]
        )
        assert args.command == "demo"
        assert args.demo_command == "prepare"
        assert args.component == "dashboard"
        assert args.seed == 1
        assert args.force is True
