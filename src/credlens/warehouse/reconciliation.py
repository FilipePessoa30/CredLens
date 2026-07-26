"""Independent Python verification of a sample of critical KPIs (Phase 5
section 15): the SQL/dbt layer must not be the only thing checking its own
arithmetic. Each check here reads the RAW SOURCE PARQUET directly with
pandas - never through dbt, never through the warehouse's own SQL - and
recomputes the same KPI from first principles, then compares it against
what the built DuckDB warehouse reports for that same run.

Tolerance, explicit and justified: source parquet stores every monetary
amount as float64 (see credlens.warehouse.build's `_table_fingerprint`
docstring and warehouse/macros/money.sql for the full story), but the
warehouse's staging layer casts those values to DECIMAL(18,2) before any
aggregation. A DECIMAL(18,2) cast can move an individual value by at most
half a cent (0.005) versus its float64 original. For a sum over N rows,
the worst-case accumulated drift is N * 0.005 - for the smoke/sample
scales this project uses (hundreds to low thousands of rows per table),
that is at most a few reais on amounts that are themselves usually in the
thousands to hundreds of thousands. A tolerance of max(0.01, 0.1% of the
expected value) comfortably absorbs that rounding while still catching a
genuine arithmetic bug (a missing join filter, a wrong sign, a dropped
table) - both of those tend to produce differences far larger than 0.1%.
Ratios (approval_rate, par90, cure_rate) are dimensionless counts-over-counts
with no decimal rounding involved on either side, so they use a tight
absolute tolerance of 1e-6.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

_RATIO_TOLERANCE = 1e-6


def _money_tolerance(expected: float) -> float:
    return max(0.01, abs(expected) * 0.001)


@dataclass(frozen=True)
class ReconciliationCheck:
    """One independently-verified KPI for one run."""

    name: str
    run_id: str
    python_value: float
    sql_value: float
    tolerance: float
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "run_id": self.run_id,
            "python_value": self.python_value,
            "sql_value": self.sql_value,
            "tolerance": self.tolerance,
            "passed": self.passed,
            "detail": self.detail,
        }


class ReconciliationError(Exception):
    """Raised when a reconciliation check cannot be evaluated at all
    (missing data), as distinct from a check that ran and failed."""


def _check(
    name: str, run_id: str, python_value: float, sql_value: float, tolerance: float
) -> ReconciliationCheck:
    diff = abs(python_value - sql_value)
    passed = diff <= tolerance
    detail = f"python={python_value!r} sql={sql_value!r} diff={diff!r} tolerance={tolerance!r}"
    return ReconciliationCheck(name, run_id, python_value, sql_value, tolerance, passed, detail)


def _read_parquet(source_path: str, table: str) -> pd.DataFrame:
    path = Path(source_path) / f"{table}.parquet"
    if not path.is_file():
        raise ReconciliationError(f"Expected source parquet not found: '{path}'.")
    return pd.read_parquet(path)


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
    return _check("approval_rate", run_id, python_value, sql_value, _RATIO_TOLERANCE)


def reconcile_outstanding_balance(conn: Any, run_id: str, source_path: str) -> ReconciliationCheck:
    snapshots = _read_parquet(source_path, "account_monthly_snapshots")
    snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"])
    final_date = snapshots["snapshot_date"].max()
    python_value = float(
        snapshots.loc[snapshots["snapshot_date"] == final_date, "total_balance"].sum()
    )
    row = conn.execute(
        """
        select sum(total_balance)
        from main_facts.fct_account_monthly
        where run_id = ? and snapshot_date = (
            select max(snapshot_date) from main_facts.fct_account_monthly where run_id = ?
        )
        """,
        [run_id, run_id],
    ).fetchone()
    sql_value = float(row[0]) if row and row[0] is not None else 0.0
    return _check(
        "outstanding_balance", run_id, python_value, sql_value, _money_tolerance(python_value)
    )


def reconcile_par90(conn: Any, run_id: str, source_path: str) -> ReconciliationCheck:
    snapshots = _read_parquet(source_path, "account_monthly_snapshots")
    snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"])
    final_date = snapshots["snapshot_date"].max()
    final = snapshots.loc[snapshots["snapshot_date"] == final_date]
    total_balance = float(final["total_balance"].sum())
    balance_90plus = float(final.loc[final["delinquency_bucket"] == "90+", "total_balance"].sum())
    python_value = balance_90plus / total_balance if total_balance > 0 else 0.0

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
    return _check("par90", run_id, python_value, sql_value, _RATIO_TOLERANCE)


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
    return _check("cure_rate", run_id, python_value, sql_value, _RATIO_TOLERANCE)


def reconcile_write_off_amount(conn: Any, run_id: str, source_path: str) -> ReconciliationCheck:
    write_offs = _read_parquet(source_path, "write_off_events")
    python_value = float(write_offs["amount"].sum()) if len(write_offs) > 0 else 0.0

    row = conn.execute(
        "select sum(total_write_off_amount) from main_marts.mart_writeoff_recovery "
        "where run_id = ?",
        [run_id],
    ).fetchone()
    sql_value = float(row[0]) if row and row[0] is not None else 0.0
    return _check(
        "write_off_amount", run_id, python_value, sql_value, _money_tolerance(python_value or 1.0)
    )


def reconcile_recovery_amount(conn: Any, run_id: str, source_path: str) -> ReconciliationCheck:
    recoveries = _read_parquet(source_path, "recovery_events")
    python_value = float(recoveries["amount"].sum()) if len(recoveries) > 0 else 0.0

    row = conn.execute(
        "select sum(total_recovery_amount) from main_marts.mart_writeoff_recovery where run_id = ?",
        [run_id],
    ).fetchone()
    sql_value = float(row[0]) if row and row[0] is not None else 0.0
    return _check(
        "recovery_amount", run_id, python_value, sql_value, _money_tolerance(python_value or 1.0)
    )


_ALL_CHECKS = (
    reconcile_approval_rate,
    reconcile_outstanding_balance,
    reconcile_par90,
    reconcile_cure_rate,
    reconcile_write_off_amount,
    reconcile_recovery_amount,
)


def run_reconciliation(db_path: Path, sources: list[dict[str, Any]]) -> list[ReconciliationCheck]:
    """Runs every independent check for every source run in a build.
    Never returns early on a single check's failure - collects all
    results so a caller can see the full picture."""
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
