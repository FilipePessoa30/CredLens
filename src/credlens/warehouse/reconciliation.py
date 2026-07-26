"""Independent Python verification of a sample of critical KPIs (Phase 5
section 15, tightened in Phase 6 gate A): the SQL/dbt layer must not be
the only thing checking its own arithmetic. Each check here reads the RAW
SOURCE PARQUET directly with pandas - never through dbt, never through the
warehouse's own SQL - and recomputes the same KPI from first principles,
then compares it against what the built DuckDB warehouse reports for that
same run.

Monetary tolerance (Phase 6 gate A - replaces the earlier `max(0.01, 0.1%)`
rule, which was wide enough to mask a material discrepancy on a large
balance): every monetary comparison is exact in integer cents, not a
percentage band.

Why exact equality is achievable, not just "close enough": the warehouse's
staging layer (`warehouse/macros/money.sql`) casts every monetary source
column to DECIMAL(18,2) exactly ONCE, and every downstream SUM in the
marts is decimal (not floating point) addition of already-rounded values -
DECIMAL addition in DuckDB is exact, it does not re-round intermediate
sums. So there is exactly one rounding operation between the float64
source parquet and any aggregate the SQL side reports: the per-row
DECIMAL(18,2) cast. If the Python side applies that SAME single rounding
operation to each row before summing, both sides are summing an identical
multiset of exact decimal values, and the sums must match exactly - not
approximately.

The one subtlety: DuckDB's `CAST(x AS DECIMAL(18,2))` rounds half-away-
from-zero (verified empirically: `CAST(2.675 AS DECIMAL(18,2))` -> 2.68,
`CAST(1.005 AS DECIMAL(18,2))` -> 1.01), which is NOT what Python's
built-in `round()` does (banker's rounding, AND subject to float64
representation error on the source literal itself - `round(2.675, 2)`
gives 2.67 in Python, not 2.68, because 2.675 is not exactly representable
in float64). Reproducing DuckDB's exact rounding requires going through
`decimal.Decimal(str(x))` (parses the decimal STRING representation, side-
stepping the binary float imprecision) with `ROUND_HALF_UP` explicitly -
verified to match DuckDB's cast on every tested boundary case, including
the ones where plain Python `round()` disagrees with DuckDB.

Ratios (approval_rate, par90, cure_rate) involve no monetary rounding on
either side - they remain a tight absolute tolerance of 1e-6, unchanged
from Phase 5.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pandas as pd

_RATIO_TOLERANCE = 1e-6
_CENTS = Decimal("0.01")


class ReconciliationError(Exception):
    """Raised when a reconciliation check cannot be evaluated at all
    (missing data), as distinct from a check that ran and failed."""


def to_cents(value: float | Decimal | str) -> int:
    """Converts a monetary amount to integer cents using the SAME
    rounding rule as the warehouse's own DECIMAL(18,2) staging cast
    (round-half-away-from-zero on the decimal string representation, not
    the binary float) - see this module's docstring for why plain
    Python `round()` is not equivalent."""
    d = Decimal(str(value)).quantize(_CENTS, rounding=ROUND_HALF_UP)
    return int(d * 100)


def _sum_cents(series: pd.Series[float]) -> int:
    return sum(to_cents(v) for v in series)


@dataclass(frozen=True)
class ReconciliationCheck:
    """One independently-verified KPI for one run."""

    name: str
    run_id: str
    python_value: float
    sql_value: float
    unit: str  # "cents" (exact-integer-cents money check) or "ratio"
    tolerance: float
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "run_id": self.run_id,
            "python_value": self.python_value,
            "sql_value": self.sql_value,
            "unit": self.unit,
            "tolerance": self.tolerance,
            "passed": self.passed,
            "detail": self.detail,
        }


def _money_check(name: str, run_id: str, python_cents: int, sql_cents: int) -> ReconciliationCheck:
    """Exact integer-cents comparison - tolerance is 0 by construction
    (see module docstring for why zero tolerance is achievable, not
    merely aspirational, for this warehouse's specific rounding
    discipline)."""
    diff = abs(python_cents - sql_cents)
    passed = diff == 0
    detail = (
        f"python={python_cents}c sql={sql_cents}c diff={diff}c "
        f"(python=R${python_cents / 100:.2f} sql=R${sql_cents / 100:.2f})"
    )
    return ReconciliationCheck(
        name, run_id, python_cents / 100, sql_cents / 100, "cents", 0, passed, detail
    )


def _ratio_check(
    name: str, run_id: str, python_value: float, sql_value: float
) -> ReconciliationCheck:
    diff = abs(python_value - sql_value)
    passed = diff <= _RATIO_TOLERANCE
    detail = (
        f"python={python_value!r} sql={sql_value!r} diff={diff!r} tolerance={_RATIO_TOLERANCE!r}"
    )
    return ReconciliationCheck(
        name, run_id, python_value, sql_value, "ratio", _RATIO_TOLERANCE, passed, detail
    )


def _read_parquet(source_path: str, table: str) -> pd.DataFrame:
    path = Path(source_path) / f"{table}.parquet"
    if not path.is_file():
        raise ReconciliationError(f"Expected source parquet not found: '{path}'.")
    return pd.read_parquet(path)


def _sql_cents(conn: Any, sql: str, params: list[Any]) -> int:
    row = conn.execute(sql, params).fetchone()
    if row is None or row[0] is None:
        return 0
    # duckdb's Python driver returns DECIMAL columns as native
    # decimal.Decimal - never coerced through float, so no precision is
    # lost between "what SQL computed" and "what Python compares".
    value = row[0]
    if isinstance(value, Decimal):
        return int(value.quantize(_CENTS, rounding=ROUND_HALF_UP) * 100)
    return to_cents(value)


def reconcile_approval_rate(conn: Any, run_id: str, source_path: str) -> ReconciliationCheck:
    decisions = _read_parquet(source_path, "credit_decisions")
    python_value = (
        float((decisions["outcome"] == "approved").sum()) / len(decisions)
        if len(decisions) > 0
        else 0.0
    )
    row = conn.execute(
        """
        select sum(case when outcome = 'approved' then 1 else 0 end)::double
               / nullif(count(*), 0)
        from main_facts.fct_credit_decisions
        where run_id = ?
        """,
        [run_id],
    ).fetchone()
    sql_value = float(row[0]) if row and row[0] is not None else 0.0
    return _ratio_check("approval_rate", run_id, python_value, sql_value)


def reconcile_outstanding_balance(conn: Any, run_id: str, source_path: str) -> ReconciliationCheck:
    snapshots = _read_parquet(source_path, "account_monthly_snapshots")
    snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"])
    final_date = snapshots["snapshot_date"].max()
    python_cents = _sum_cents(
        snapshots.loc[snapshots["snapshot_date"] == final_date, "total_balance"]
    )
    sql_cents = _sql_cents(
        conn,
        """
        select sum(total_balance)
        from main_facts.fct_account_monthly
        where run_id = ? and snapshot_date = (
            select max(snapshot_date) from main_facts.fct_account_monthly where run_id = ?
        )
        """,
        [run_id, run_id],
    )
    return _money_check("outstanding_balance", run_id, python_cents, sql_cents)


def reconcile_par90(conn: Any, run_id: str, source_path: str) -> ReconciliationCheck:
    snapshots = _read_parquet(source_path, "account_monthly_snapshots")
    snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"])
    final_date = snapshots["snapshot_date"].max()
    final = snapshots.loc[snapshots["snapshot_date"] == final_date]
    total_balance_cents = _sum_cents(final["total_balance"])
    balance_90plus = final.loc[final["delinquency_bucket"] == "90+", "total_balance"]
    balance_90plus_cents = _sum_cents(balance_90plus)
    python_value = balance_90plus_cents / total_balance_cents if total_balance_cents > 0 else 0.0

    row = conn.execute(
        """
        select par90
        from main_marts.mart_delinquency_monthly
        where run_id = ? and snapshot_date = (
            select max(snapshot_date) from main_marts.mart_delinquency_monthly where run_id = ?
        )
        """,
        [run_id, run_id],
    ).fetchone()
    sql_value = float(row[0]) if row and row[0] is not None else 0.0
    return _ratio_check("par90", run_id, python_value, sql_value)


def reconcile_cure_rate(conn: Any, run_id: str, source_path: str) -> ReconciliationCheck:
    snapshots = _read_parquet(source_path, "account_monthly_snapshots")
    snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"])
    snapshots = snapshots.sort_values(["contract_id", "snapshot_date"])
    snapshots["prior_status"] = snapshots.groupby("contract_id")["status"].shift(1)
    is_cure = (snapshots["status"] == "active") & (snapshots["prior_status"] == "delinquent")
    prior_delinquent = snapshots["prior_status"] == "delinquent"
    python_value = (
        float(is_cure.sum()) / float(prior_delinquent.sum()) if prior_delinquent.sum() > 0 else 0.0
    )

    row = conn.execute(
        """
        select sum(cures)::double / nullif(sum(prior_month_delinquent_count), 0)
        from main_marts.mart_delinquency_monthly
        where run_id = ?
        """,
        [run_id],
    ).fetchone()
    sql_value = float(row[0]) if row and row[0] is not None else 0.0
    return _ratio_check("cure_rate", run_id, python_value, sql_value)


def reconcile_write_off_amount(conn: Any, run_id: str, source_path: str) -> ReconciliationCheck:
    write_offs = _read_parquet(source_path, "write_off_events")
    python_cents = _sum_cents(write_offs["amount"]) if len(write_offs) > 0 else 0
    sql_cents = _sql_cents(
        conn,
        "select sum(total_write_off_amount) from main_marts.mart_writeoff_recovery "
        "where run_id = ?",
        [run_id],
    )
    return _money_check("write_off_amount", run_id, python_cents, sql_cents)


def reconcile_recovery_amount(conn: Any, run_id: str, source_path: str) -> ReconciliationCheck:
    recoveries = _read_parquet(source_path, "recovery_events")
    python_cents = _sum_cents(recoveries["amount"]) if len(recoveries) > 0 else 0
    sql_cents = _sql_cents(
        conn,
        "select sum(total_recovery_amount) from main_marts.mart_writeoff_recovery where run_id = ?",
        [run_id],
    )
    return _money_check("recovery_amount", run_id, python_cents, sql_cents)


def reconcile_paid_amount(conn: Any, run_id: str, source_path: str) -> ReconciliationCheck:
    """cumulative_paid at the run's final snapshot_date (POR-004) -
    STOCK measure, so only the final month's own already-cumulative
    figure is compared, never summed across snapshot_date."""
    snapshots = _read_parquet(source_path, "account_monthly_snapshots")
    snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"])
    final_date = snapshots["snapshot_date"].max()
    python_cents = _sum_cents(
        snapshots.loc[snapshots["snapshot_date"] == final_date, "cumulative_paid"]
    )
    sql_cents = _sql_cents(
        conn,
        """
        select sum(cumulative_paid)
        from main_facts.fct_account_monthly
        where run_id = ? and snapshot_date = (
            select max(snapshot_date) from main_facts.fct_account_monthly where run_id = ?
        )
        """,
        [run_id, run_id],
    )
    return _money_check("paid_amount", run_id, python_cents, sql_cents)


def reconcile_scheduled_amount(conn: Any, run_id: str, source_path: str) -> ReconciliationCheck:
    """Total scheduled_total across every installment ever scheduled for
    this run (POR-003) - a FLOW total (the whole amortization schedule as
    originally written), not filtered to one period; matches
    mart_portfolio_monthly's own scheduled_amount_total column, which is
    documented as the same whole-of-schedule total, not a monthly-due
    figure (see warehouse/kpi_catalog.yml POR-003's grain note)."""
    installments = _read_parquet(source_path, "installments")
    python_cents = _sum_cents(installments["scheduled_total"]) if len(installments) > 0 else 0
    sql_cents = _sql_cents(
        conn,
        "select sum(scheduled_total) from main_facts.fct_installments where run_id = ?",
        [run_id],
    )
    return _money_check("scheduled_amount", run_id, python_cents, sql_cents)


_ALL_CHECKS = (
    reconcile_approval_rate,
    reconcile_outstanding_balance,
    reconcile_par90,
    reconcile_cure_rate,
    reconcile_write_off_amount,
    reconcile_recovery_amount,
    reconcile_paid_amount,
    reconcile_scheduled_amount,
)


def run_reconciliation(db_path: Path, sources: list[dict[str, Any]]) -> list[ReconciliationCheck]:
    """Runs every independent check for every source run in a build.
    Never returns early on a single check's failure - collects all
    results so a caller can see the full picture.

    Phase 6 gate C: verifies every source's raw parquet/manifest against
    what the build itself recorded BEFORE running a single check - the
    raw layer is external DuckDB views over those same files, so a file
    changed after the build would otherwise silently change what
    reconciliation compares against, without the build's own fingerprint
    ever having been wrong. Raises RawIntegrityError, not a reconciliation
    failure, if anything no longer matches."""
    from credlens.warehouse.integrity import verify_build_sources

    verify_build_sources(sources)

    import duckdb

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        results: list[ReconciliationCheck] = []
        for source in sources:
            run_id = str(source["run_id"])
            source_path = str(source["source_path"])
            for check_fn in _ALL_CHECKS:
                results.append(check_fn(conn, run_id, source_path))
        return results
    finally:
        conn.close()
