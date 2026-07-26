"""Named demo analytical queries against an already-built warehouse
(Phase 5 section 13: `credlens warehouse query --build-id --name <NAME>`).

Deliberately NOT an executive report or a dashboard - just a fixed set of
read-only SQL queries against the marts layer, useful to sanity-check a
build interactively. Every mart lives in a schema whose name ends in
"marts" (dbt-duckdb prefixes the configured `+schema: marts` with the
target's own default schema - observed as "main_marts"), so table lookup
is done by suffix match rather than hardcoding that prefix.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# name -> mart table name. Every entry here must correspond to a real
# model under warehouse/models/marts/ - see warehouse/models/marts/_marts__models.yml.
NAMED_QUERIES: dict[str, str] = {
    "credit_funnel": "mart_credit_funnel_monthly",
    "portfolio_monthly": "mart_portfolio_monthly",
    "delinquency_monthly": "mart_delinquency_monthly",
    "vintage_cohorts": "mart_vintage_cohorts",
    "roll_rates": "mart_roll_rates",
    "cure_and_redefault": "mart_cure_and_redefault",
    "collections_performance": "mart_collections_performance",
    "writeoff_recovery": "mart_writeoff_recovery",
    "scenario_comparison": "mart_scenario_comparison",
}


class QueryError(Exception):
    """Raised when a named query is unknown, or its table isn't in the build."""


def _qualified_table(conn: Any, table: str) -> str:
    row = conn.execute(
        "select table_schema from information_schema.tables "
        "where table_name = ? and table_schema like '%marts'",
        [table],
    ).fetchone()
    if row is None:
        raise QueryError(
            f"Table '{table}' was not found in a *marts schema of this build - "
            "was the build's `dbt build` step successful?"
        )
    return f'"{row[0]}"."{table}"'


def run_named_query(db_path: Path, name: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Runs one fixed, named, read-only demo query. Returns (column_names, rows)."""
    if name not in NAMED_QUERIES:
        available = ", ".join(sorted(NAMED_QUERIES))
        raise QueryError(f"Unknown query name '{name}'. Available: {available}")
    if not db_path.is_file():
        raise QueryError(f"No database file at '{db_path}'.")

    import duckdb

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        qualified = _qualified_table(conn, NAMED_QUERIES[name])
        cursor = conn.execute(f"select * from {qualified} order by 1")
        columns = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
    finally:
        conn.close()
    return columns, rows
