"""Tests for credlens.warehouse.reconciliation: independent Python
verification of a sample of critical KPIs, reading raw source parquet
directly (never through dbt/SQL) - Phase 5 section 15. Uses a real
`contract_coverage` build (deliberately rich in rare states, so write-offs/
recoveries/cures are actually non-zero, not just plausible edge cases)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from credlens.generation.config import load_generation_config
from credlens.generation.orchestrator import generate_scenario
from credlens.warehouse.build import (
    _rmtree_with_retry,
    build_dir_for,
    load_build_manifest,
    run_build,
)
from credlens.warehouse.reconciliation import run_reconciliation

_SEED = 615_303
_BUILD_ID = "BUILD_pytest_reconciliation"


@pytest.fixture(scope="module")
def a_real_run() -> Iterator[str]:
    outcome = generate_scenario(
        scenario="contract_coverage", scale_name="smoke", seed=_SEED, force=True
    )
    yield outcome.generation_run_id
    config = load_generation_config()
    for base in (config.output.operational_dir, config.output.truth_dir):
        path = Path(base) / outcome.generation_run_id
        if path.exists():
            shutil.rmtree(path)


@pytest.fixture(scope="module")
def a_built_warehouse(a_real_run: str) -> Iterator[str]:
    manifest = run_build(run_id=a_real_run, build_id=_BUILD_ID, force=True)
    assert manifest.final_status == "success"
    yield manifest.build_id
    build_dir = build_dir_for(_BUILD_ID)
    if build_dir.exists():
        try:
            _rmtree_with_retry(build_dir)
        except PermissionError:
            shutil.rmtree(build_dir, ignore_errors=True)


class TestRunReconciliation:
    def test_all_checks_pass_against_a_real_build(self, a_built_warehouse: str) -> None:
        manifest = load_build_manifest(a_built_warehouse)
        results = run_reconciliation(Path(manifest.db_path), manifest.sources)

        assert len(results) == 6
        names = {r.name for r in results}
        assert names == {
            "approval_rate",
            "outstanding_balance",
            "par90",
            "cure_rate",
            "write_off_amount",
            "recovery_amount",
        }
        for r in results:
            assert r.passed, r.detail

    def test_at_least_one_check_has_a_nontrivial_nonzero_value(
        self, a_built_warehouse: str
    ) -> None:
        # contract_coverage is deliberately extreme-parameter and should
        # produce real write-offs/cures, not just an all-zeros pass -
        # guards against the reconciliation silently only ever comparing
        # 0.0 == 0.0.
        manifest = load_build_manifest(a_built_warehouse)
        results = run_reconciliation(Path(manifest.db_path), manifest.sources)
        assert any(r.python_value != 0.0 for r in results if r.name == "write_off_amount")
        assert any(r.python_value != 0.0 for r in results if r.name == "cure_rate")

    def test_tolerance_is_never_zero(self, a_built_warehouse: str) -> None:
        manifest = load_build_manifest(a_built_warehouse)
        results = run_reconciliation(Path(manifest.db_path), manifest.sources)
        for r in results:
            assert r.tolerance > 0
