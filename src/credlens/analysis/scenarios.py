"""Paired scenario comparison (Phase 6 section 12): respects the CRN
(common random numbers) design - policy_expansion/policy_tightening share
the exact same `application_id` population as baseline (see
docs/common_random_numbers.md), so "did the policy change help or hurt"
can be answered two genuinely different ways that must never be
conflated:

  1. MECHANICAL effect: how many additional/fewer applications got
     booked (composition change).
  2. PERFORMANCE effect: among applications booked in BOTH runs (the
     SHARED population), did their outcomes differ? - isolates whether
     the scenario changed underwriting decisions on the margin from
     whether it changed how the SAME contracts performed (it should not,
     since payment behavior config is identical for baseline/policy
     scenarios - a real difference here would indicate a CRN bug, not a
     policy effect).

Matched by `application_id`, never `contract_id` - contract ids are
assigned in scenario-specific order among approved applications, so the
same underlying application can get a DIFFERENT contract_id string in
baseline vs. a policy scenario even though application_id is identical.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from credlens.analysis.metrics import MIN_SEGMENT_OBSERVATIONS, _df
from credlens.analysis.sample_policy import SampleClassification, combine_classifications


@dataclass(frozen=True)
class CompositionVsPerformance:
    suite_id: str
    scenario: str
    baseline_run_id: str
    scenario_run_id: str
    shared_booked_count: int
    baseline_only_count: int
    scenario_only_count: int
    shared_par90: float | None
    marginal_par90: float | None
    shared_outstanding_balance: float
    marginal_outstanding_balance: float
    low_sample: bool
    # The three-tier classification (Phase 7 gate B) of the LEAST
    # favorable of shared/baseline-only/scenario-only counts - never
    # 'adequate' if any side of the comparison is not.
    sample_classification: SampleClassification

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "scenario": self.scenario,
            "baseline_run_id": self.baseline_run_id,
            "scenario_run_id": self.scenario_run_id,
            "shared_booked_count": self.shared_booked_count,
            "baseline_only_count": self.baseline_only_count,
            "scenario_only_count": self.scenario_only_count,
            "shared_par90": self.shared_par90,
            "marginal_par90": self.marginal_par90,
            "shared_outstanding_balance": self.shared_outstanding_balance,
            "marginal_outstanding_balance": self.marginal_outstanding_balance,
            "low_sample": self.low_sample,
            "sample_classification": self.sample_classification,
        }


def _run_ids_for(conn: Any, suite_id: str, scenario: str) -> str:
    row = conn.execute(
        "select run_id from main_dimensions.dim_run where suite_id = ? and scenario = ?",
        [suite_id, scenario],
    ).fetchone()
    if row is None:
        raise ValueError(f"No run found for suite_id={suite_id!r} scenario={scenario!r}.")
    return str(row[0])


def composition_vs_performance(conn: Any, suite_id: str, scenario: str) -> CompositionVsPerformance:
    """Only meaningful for policy_expansion/policy_tightening - both
    booking a genuinely different (superset/subset) set of applications
    than baseline, on the SAME underlying application population."""
    if scenario not in ("policy_expansion", "policy_tightening"):
        raise ValueError(
            f"composition_vs_performance only applies to policy_expansion/policy_tightening, "
            f"got {scenario!r}."
        )
    baseline_run_id = _run_ids_for(conn, suite_id, "baseline")
    scenario_run_id = _run_ids_for(conn, suite_id, scenario)

    booked = _df(
        conn,
        """
        with baseline_booked as (
            select a.application_id, c.contract_key
            from main_facts.fct_applications a
            join main_facts.fct_contracts c on a.application_key = c.application_key
            where a.run_id = ?
        ),
        scenario_booked as (
            select a.application_id, c.contract_key
            from main_facts.fct_applications a
            join main_facts.fct_contracts c on a.application_key = c.application_key
            where a.run_id = ?
        )
        select
            coalesce(b.application_id, s.application_id) as application_id,
            b.contract_key as baseline_contract_key,
            s.contract_key as scenario_contract_key,
            case
                when b.contract_key is not null and s.contract_key is not null then 'shared'
                when b.contract_key is not null then 'baseline_only'
                else 'scenario_only'
            end as membership
        from baseline_booked b
        full outer join scenario_booked s on b.application_id = s.application_id
        """,
        [baseline_run_id, scenario_run_id],
    )

    shared_count = int((booked["membership"] == "shared").sum())
    baseline_only_count = int((booked["membership"] == "baseline_only").sum())
    scenario_only_count = int((booked["membership"] == "scenario_only").sum())

    shared_contract_keys = booked.loc[
        booked["membership"] == "shared", "scenario_contract_key"
    ].dropna()
    marginal_contract_keys = booked.loc[
        booked["membership"] == "scenario_only", "scenario_contract_key"
    ].dropna()

    def _final_month_par90_and_balance(contract_keys: pd.Series) -> tuple[float | None, float]:
        if len(contract_keys) == 0:
            return None, 0.0
        placeholders = ",".join("?" for _ in contract_keys)
        row = conn.execute(
            f"""
            with final_month as (
                select contract_key, max(snapshot_date) as final_date
                from main_facts.fct_account_monthly
                where contract_key in ({placeholders})
                group by 1
            )
            select
                sum(a.total_balance) as outstanding_balance,
                sum(case when a.dpd_bucket = '90+' then a.total_balance else 0 end)
                    / nullif(sum(a.total_balance), 0) as par90
            from main_facts.fct_account_monthly a
            join final_month f on a.contract_key = f.contract_key and a.snapshot_date = f.final_date
            """,
            list(contract_keys),
        ).fetchone()
        if row is None or row[0] is None:
            return None, 0.0
        return (float(row[1]) if row[1] is not None else None), float(row[0])

    shared_par90, shared_balance = _final_month_par90_and_balance(shared_contract_keys)
    marginal_par90, marginal_balance = _final_month_par90_and_balance(marginal_contract_keys)

    return CompositionVsPerformance(
        suite_id=suite_id,
        scenario=scenario,
        baseline_run_id=baseline_run_id,
        scenario_run_id=scenario_run_id,
        shared_booked_count=shared_count,
        baseline_only_count=baseline_only_count,
        scenario_only_count=scenario_only_count,
        shared_par90=shared_par90,
        marginal_par90=marginal_par90,
        shared_outstanding_balance=shared_balance,
        marginal_outstanding_balance=marginal_balance,
        low_sample=(
            shared_count < MIN_SEGMENT_OBSERVATIONS
            or max(baseline_only_count, scenario_only_count) < MIN_SEGMENT_OBSERVATIONS
        ),
        # Mirrors low_sample's own semantics: for policy_expansion/
        # tightening, one of baseline_only/scenario_only is STRUCTURALLY
        # near-zero by design (expansion should not remove contracts,
        # tightening should not add any) - that near-zero side is not a
        # sampling defect, so only the LARGER of the two exclusive groups
        # is judged, same as the max() used for low_sample above.
        sample_classification=combine_classifications(
            shared_count, max(baseline_only_count, scenario_only_count)
        ),
    )
