"""Tests for credlens.warehouse.reconciliation: independent Python
verification of a sample of critical KPIs, reading raw source parquet
directly (never through dbt/SQL) - Phase 5 section 15, tightened in Phase
6 gate A (exact-cents monetary comparison, replacing the earlier
percentage-band tolerance). Uses a real `contract_coverage` build
(deliberately rich in rare states, so write-offs/recoveries/cures are
actually non-zero, not just plausible edge cases)."""

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
from credlens.warehouse.reconciliation import _money_check, run_reconciliation, to_cents

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

        assert len(results) == 8
        names = {r.name for r in results}
        assert names == {
            "approval_rate",
            "outstanding_balance",
            "par90",
            "cure_rate",
            "write_off_amount",
            "recovery_amount",
            "paid_amount",
            "scheduled_amount",
        }
        for r in results:
            assert r.passed, r.detail

    def test_money_checks_are_exact_zero_tolerance(self, a_built_warehouse: str) -> None:
        manifest = load_build_manifest(a_built_warehouse)
        results = run_reconciliation(Path(manifest.db_path), manifest.sources)
        money_checks = [r for r in results if r.unit == "cents"]
        # 5 money-typed checks (outstanding_balance, write_off_amount,
        # recovery_amount, paid_amount, scheduled_amount) for the 1 run
        # this fixture builds from.
        assert len(money_checks) == 5
        for r in money_checks:
            assert r.tolerance == 0, r.detail

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


class TestToCents:
    """Regression guard for the rounding-mode fix itself (Phase 6 gate A):
    to_cents() must match DuckDB's own CAST(x AS DECIMAL(18,2)) rounding
    (round-half-away-from-zero on the decimal string) exactly, including
    on the specific boundary cases where Python's built-in round() -
    banker's rounding, plus float64 representation error on the source
    literal - disagrees with DuckDB. Values verified empirically against
    a live DuckDB connection while implementing this fix."""

    @pytest.mark.parametrize(
        ("value", "expected_cents"),
        [
            (0.005, 1),
            (0.015, 2),
            (0.025, 3),
            (0.035, 4),
            (0.045, 5),
            (1.005, 101),
            (2.675, 268),
            (100.0, 10000),
            (0.0, 0),
        ],
    )
    def test_matches_duckdb_decimal_cast_rounding(self, value: float, expected_cents: int) -> None:
        assert to_cents(value) == expected_cents

    def test_plain_python_round_would_have_disagreed(self) -> None:
        # Documents WHY to_cents() cannot just be round(value * 100) -
        # this is the exact failure mode the Decimal(str(...)) +
        # ROUND_HALF_UP implementation avoids.
        value = 2.675
        assert round(value, 2) != 2.68  # plain Python round disagrees with DuckDB here
        assert to_cents(value) == 268  # to_cents() agrees with DuckDB


class TestOldToleranceRuleWasInsufficient:
    """The mandatory negative test (Phase 6 gate A section 4.3): proves
    the pre-Phase-6 tolerance rule (max(0.01, 0.1% of expected), see
    CHANGELOG [0.6.0]) was wide enough to mask a real, material
    discrepancy on a large balance, and that the new exact-cents rule
    catches the SAME discrepancy."""

    def test_old_rule_would_have_passed_a_material_discrepancy(self) -> None:
        expected_reais = 1_000_000.00
        old_tolerance = max(0.01, abs(expected_reais) * 0.001)  # the old formula, verbatim
        material_diff_reais = 500.00  # half a million cents - not a rounding artifact

        assert old_tolerance == 1000.00
        assert material_diff_reais < old_tolerance, (
            "sanity check: this diff must fall inside the OLD rule's own tolerance "
            "band for the test to demonstrate anything"
        )

    def test_new_rule_rejects_the_same_discrepancy(self) -> None:
        expected_reais = 1_000_000.00
        material_diff_reais = 500.00

        python_cents = to_cents(expected_reais)
        sql_cents = to_cents(expected_reais - material_diff_reais)
        check = _money_check("outstanding_balance", "RUN_synthetic_test", python_cents, sql_cents)

        assert not check.passed, (
            "a R$500.00 discrepancy on a R$1,000,000.00 balance must fail exact-cents "
            "reconciliation, even though it would have passed the old 0.1% rule"
        )
        assert check.tolerance == 0

    def test_new_rule_accepts_a_genuine_rounding_only_difference(self) -> None:
        # A one-cent difference from independent rounding of the SAME
        # underlying value must NOT occur once both sides use to_cents()
        # consistently - this test proves the new rule isn't simply
        # "stricter" in a way that produces false positives on identical
        # inputs.
        value = 123456.785
        python_cents = to_cents(value)
        sql_cents = to_cents(value)
        check = _money_check("outstanding_balance", "RUN_synthetic_test", python_cents, sql_cents)
        assert check.passed
