"""SQL-first metric queries against a built warehouse (Phase 6 section
10). Every function here is a thin wrapper: the actual aggregation logic
lives in SQL (either an existing dbt mart, or a documented ad hoc query
against the warehouse's facts/dimensions for segmentations no mart
covers), never reimplemented in pandas. Each query documents purpose,
grain, filters, ordering, and null handling directly above the SQL, per
Phase 6 section 10's requirement.

Every function takes an open, read-only DuckDB connection (see
`connect()`) and returns a `pandas.DataFrame` - callers (charts,
reporting, the CLI) never write their own SQL against the warehouse.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd

from credlens.analysis.sample_policy import classify_sample_size, load_sample_policy

# Minimum observations a segmented breakdown must have before its metric
# is reported un-suppressed. Phase 6 used a flat cutoff of 10; Phase 7
# gate B replaced it with the versioned, three-tier policy in
# `credlens.analysis.sample_policy` (insufficient / limited / adequate -
# see `analysis/specifications/segmentation_policy.yaml`). This constant
# is kept, at the policy's `insufficient_below` value, purely so
# `low_sample` (a plain boolean "insufficient" flag) stays available for
# callers that only need a yes/no suppression signal; new code should
# prefer the `sample_classification` column these functions now also add.
MIN_SEGMENT_OBSERVATIONS = load_sample_policy().insufficient_below


@contextmanager
def connect(db_path: Path) -> Iterator[Any]:
    import duckdb

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        yield conn
    finally:
        conn.close()


def _df(conn: Any, sql: str, params: list[Any] | None = None) -> pd.DataFrame:
    cursor = conn.execute(sql, params or [])
    columns = [d[0] for d in cursor.description]
    return pd.DataFrame(cursor.fetchall(), columns=columns)


def _mart(conn: Any, table: str, suite_id: str) -> pd.DataFrame:
    """Every named mart, filtered to one suite_id and ordered
    deterministically by every non-measure column - grain and filters are
    whatever that mart's own header comment documents (see
    warehouse/models/marts/*.sql)."""
    schema_row = conn.execute(
        "select table_schema from information_schema.tables "
        "where table_name = ? and table_schema like '%marts'",
        [table],
    ).fetchone()
    if schema_row is None:
        raise ValueError(f"Mart table '{table}' not found in this build.")
    qualified = f'"{schema_row[0]}"."{table}"'
    return _df(conn, f"select * from {qualified} where suite_id = ? order by all", [suite_id])


# --- Marts, filtered to one suite (Phase 6's primary analysis grain) --------


def funnel_monthly(conn: Any, suite_id: str) -> pd.DataFrame:
    """Purpose: credit funnel (submitted -> decisioned -> approved ->
    booked) by month and channel. Grain: (run_id, submitted_month,
    channel). Filters: suite_id. Nulls: none expected (every application
    has a channel). Source: mart_credit_funnel_monthly."""
    return _mart(conn, "mart_credit_funnel_monthly", suite_id)


def portfolio_monthly(conn: Any, suite_id: str) -> pd.DataFrame:
    """Purpose: portfolio stock (balance, active contracts) plus that
    month's own flow (scheduled/paid/partial/prepayment). Grain: (run_id,
    snapshot_date) - STOCK, never sum across snapshot_date for one
    contract; safe to sum across contracts within one date. Source:
    mart_portfolio_monthly."""
    return _mart(conn, "mart_portfolio_monthly", suite_id)


def delinquency_monthly(conn: Any, suite_id: str) -> pd.DataFrame:
    """Purpose: PAR30/60/90, contract-count delinquency rates, cures, new
    delinquencies. Grain: (run_id, snapshot_date). Source:
    mart_delinquency_monthly."""
    return _mart(conn, "mart_delinquency_monthly", suite_id)


def vintage_cohorts(conn: Any, suite_id: str) -> pd.DataFrame:
    """Purpose: origination-cohort incidence by months-on-book (MOB).
    Grain: (run_id, vintage_month, months_on_book). Limitation: compare
    cohorts only up to max_mob_observed_for_cohort (both must have
    reached that MOB). Source: mart_vintage_cohorts."""
    return _mart(conn, "mart_vintage_cohorts", suite_id)


def roll_rates(conn: Any, suite_id: str) -> pd.DataFrame:
    """Purpose: month-over-month DPD bucket transitions for the SAME
    contract (never cross-contract). Grain: (run_id, snapshot_date,
    from_bucket, to_bucket). Source: mart_roll_rates."""
    return _mart(conn, "mart_roll_rates", suite_id)


def cure_and_redefault(conn: Any, suite_id: str) -> pd.DataFrame:
    """Purpose: per-contract cure/relapse history. Grain: (run_id,
    contract_key) - aggregate this DataFrame yourself for a rate (cure_rate
    = was_ever_cured.mean() is WRONG - use SQL sums, see
    warehouse/analyses/redefault_rate.sql for the correct aggregate
    query). Source: mart_cure_and_redefault."""
    return _mart(conn, "mart_cure_and_redefault", suite_id)


def collections_performance(conn: Any, suite_id: str) -> pd.DataFrame:
    """Purpose: collections contact activity vs. the delinquent
    population eligible that month. Grain: (run_id, event_month). Source:
    mart_collections_performance."""
    return _mart(conn, "mart_collections_performance", suite_id)


def writeoff_recovery(conn: Any, suite_id: str) -> pd.DataFrame:
    """Purpose: write-off and recovery amounts/counts. Grain: (run_id,
    write_off_month). Source: mart_writeoff_recovery."""
    return _mart(conn, "mart_writeoff_recovery", suite_id)


def scenario_comparison(conn: Any, suite_id: str) -> pd.DataFrame:
    """Purpose: baseline-vs-scenario deltas (approval rate, DPD90+ rate,
    write-off count), whole-run. Grain: (suite_id, scenario != 'baseline').
    Source: mart_scenario_comparison."""
    return _df(
        conn,
        "select * from main_marts.mart_scenario_comparison where suite_id = ? order by all",
        [suite_id],
    )


def macro_stress_pre_post(conn: Any, suite_id: str) -> pd.DataFrame:
    """Purpose: baseline-vs-stress compared within the pre-shock and
    post-shock periods separately. Grain: (suite_id, period). Source:
    mart_macro_stress_pre_post."""
    return _df(
        conn,
        "select * from main_marts.mart_macro_stress_pre_post where suite_id = ? order by all",
        [suite_id],
    )


# --- Segmentations no existing mart covers (Phase 6 section 11) ------------


def funnel_by_channel_and_scenario(conn: Any, suite_id: str) -> pd.DataFrame:
    """Purpose: approval/booking rate by channel, within each scenario -
    where do the biggest funnel losses happen, and does that change by
    channel. Grain: (run_id, scenario, channel). Filters: suite_id.
    Exclusions: none. Nulls: none (channel is not-null on every
    application). Suppression: rows with fewer than
    MIN_SEGMENT_OBSERVATIONS decisioned applications are flagged
    low_sample rather than dropped."""
    df = _df(
        conn,
        """
        select
            b.run_id,
            r.scenario,
            b.channel,
            sum(b.applications_submitted) as applications_submitted,
            sum(b.decisioned_applications) as decisioned_applications,
            sum(b.approved_count) as approved_count,
            sum(b.booked_count) as booked_count,
            case when sum(b.decisioned_applications) > 0
                then sum(b.approved_count)::double / sum(b.decisioned_applications)
            end as approval_rate,
            case when sum(b.approved_count) > 0
                then sum(b.booked_count)::double / sum(b.approved_count)
            end as booking_rate_of_approved
        from main_marts.mart_credit_funnel_monthly b
        join main_dimensions.dim_run r on b.run_id = r.run_id
        where b.suite_id = ?
        group by 1, 2, 3
        order by all
        """,
        [suite_id],
    )
    df["low_sample"] = df["decisioned_applications"] < MIN_SEGMENT_OBSERVATIONS
    df["sample_classification"] = df["decisioned_applications"].map(classify_sample_size)
    return df


def portfolio_by_region_and_channel(conn: Any, suite_id: str) -> pd.DataFrame:
    """Purpose: outstanding balance concentration by region x channel, at
    each run's final observed snapshot. Grain: (run_id, region, channel).
    Filters: suite_id, snapshot_date = that run's own max snapshot_date
    (never mixed across dates - STOCK). `region` is sourced from
    fairness_attributes - an EVALUATION-ONLY field (see
    docs/fairness_data_design.md) - used here strictly as an aggregate,
    retrospective audit breakdown, never to target or score an individual
    contract; this query is never joined back into any decisioning path.
    Suppression: fewer than MIN_SEGMENT_OBSERVATIONS contracts ->
    low_sample."""
    df = _df(
        conn,
        """
        with final_month as (
            select run_id, max(snapshot_date) as final_date
            from main_facts.fct_account_monthly
            group by 1
        )
        select
            a.run_id,
            fa.region,
            app.channel,
            count(*) as contracts,
            sum(a.total_balance) as outstanding_balance
        from main_facts.fct_account_monthly a
        join final_month f on a.run_id = f.run_id and a.snapshot_date = f.final_date
        join main_facts.fct_contracts c on a.contract_key = c.contract_key
        join main_facts.fct_applications app on c.application_key = app.application_key
        join main_staging.stg_fairness_attributes fa on app.application_key = fa.application_key
        where a.suite_id = ?
        group by 1, 2, 3
        order by all
        """,
        [suite_id],
    )
    df["low_sample"] = df["contracts"] < MIN_SEGMENT_OBSERVATIONS
    df["sample_classification"] = df["contracts"].map(classify_sample_size)
    return df


def policy_version_comparison(conn: Any, suite_id: str) -> pd.DataFrame:
    """Purpose: approval rate by policy version, within each run - proves
    (or disproves) that a policy_expansion/tightening scenario actually
    changed the cutoff a decision was made under. Grain: (run_id,
    policy_version_id). Suppression: fewer than MIN_SEGMENT_OBSERVATIONS
    decisions -> low_sample."""
    df = _df(
        conn,
        """
        select
            d.run_id,
            r.scenario,
            pv.policy_version_id,
            count(*) as decisions,
            sum(case when d.outcome = 'approved' then 1 else 0 end) as approved,
            sum(case when d.outcome = 'approved' then 1 else 0 end)::double
                / nullif(count(*), 0) as approval_rate
        from main_facts.fct_credit_decisions d
        join main_dimensions.dim_policy pv on d.policy_version_key = pv.policy_version_key
        join main_dimensions.dim_run r on d.run_id = r.run_id
        where r.suite_id = ?
        group by 1, 2, 3
        order by all
        """,
        [suite_id],
    )
    df["low_sample"] = df["decisions"] < MIN_SEGMENT_OBSERVATIONS
    df["sample_classification"] = df["decisions"].map(classify_sample_size)
    return df


def credit_risk_segment_summary(conn: Any, suite_id: str) -> pd.DataFrame:
    """Purpose: approval rate by product / bureau_score_bucket /
    income_band / contract_value_band (Phase 7 dashboard filters - not
    covered by any existing mart, which never groups by product or by
    application-feature attributes). Grain: (run_id, product,
    bureau_score_bucket, income_band, contract_value_band).
    `product`/`bureau_score_bucket` are direct categorical columns
    (fct_applications/stg_application_features); `income_band`/
    `contract_value_band` are display-only quartile buckets (SQL
    ntile(4) over declared_income/requested_amount) computed here for
    dashboard filtering, never a business/credit decision rule. Filters:
    suite_id. Suppression: fewer than MIN_SEGMENT_OBSERVATIONS decisions
    -> low_sample."""
    df = _df(
        conn,
        """
        with banded as (
            select
                d.run_id,
                d.application_key,
                d.outcome,
                a.product,
                saf.bureau_score_bucket,
                'Q' || ntile(4) over (partition by d.run_id order by saf.declared_income)
                    as income_band,
                'Q' || ntile(4) over (partition by d.run_id order by saf.requested_amount)
                    as contract_value_band
            from main_facts.fct_credit_decisions d
            join main_staging.stg_application_features saf
                on d.application_key = saf.application_key and d.run_id = saf.run_id
            join main_facts.fct_applications a
                on d.application_key = a.application_key and d.run_id = a.run_id
            join main_dimensions.dim_run r on d.run_id = r.run_id
            where r.suite_id = ?
        )
        select
            run_id,
            product,
            bureau_score_bucket,
            income_band,
            contract_value_band,
            count(*) as decisions,
            sum(case when outcome = 'approved' then 1 else 0 end) as approved,
            sum(case when outcome = 'approved' then 1 else 0 end)::double
                / nullif(count(*), 0) as approval_rate
        from banded
        group by 1, 2, 3, 4, 5
        order by all
        """,
        [suite_id],
    )
    df["low_sample"] = df["decisions"] < MIN_SEGMENT_OBSERVATIONS
    df["sample_classification"] = df["decisions"].map(classify_sample_size)
    return df
