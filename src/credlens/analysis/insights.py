"""Verifiable insights registry (Phase 7 gate D).

Every insight here is GENERATED from already-validated outputs an
`credlens analysis run` produced (the tables under
`reports/portfolio_analysis/tables/`, its `manifest.json`) plus, when
available, the Phase 7 gate A multi-seed robustness sweep
(`reports/synthetic_validation/multiseed_robustness.json`) and the public
benchmark appendix (`credlens.analysis.benchmark`) - no number here is
hand-typed. Regenerate with `generate_insights()` whenever the underlying
build changes; never hand-edit `reports/portfolio_analysis/insights.yml`.

Every insight declares its own provenance (Phase 7 gate C,
`credlens.analysis.data_provenance`) and sample-size classification
(Phase 7 gate B, `credlens.analysis.sample_policy`) - a segment classified
`insufficient` must never be surfaced as an executive-ready finding (see
`is_executive_ready`), and neither must a `statement_type` of `hypothesis`
or `unsupported`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml

from credlens.analysis.data_provenance import get_table_provenance
from credlens.analysis.sample_policy import classify_sample_size

StatementType = Literal[
    "observed_synthetic_result",
    "public_benchmark_description",
    "scenario_comparison",
    "analytical_inference",
    "hypothesis",
    "unsupported",
]

# statement_type values that may NEVER be surfaced as an executive
# conclusion (Phase 7 gate D section 7.1: "Nenhum item unsupported pode
# aparecer como conclusao executiva" - hypothesis is excluded for the
# same reason: it is explicitly not yet demonstrated).
_NOT_EXECUTIVE_READY: frozenset[StatementType] = frozenset({"unsupported", "hypothesis"})

# query_function -> the dbt mart it reads (Phase 6's own SQL-first
# design, see credlens.analysis.metrics's docstrings) - a small, explicit
# lookup rather than re-parsing docstrings.
_TABLE_TO_DBT_MODEL: dict[str, str] = {
    "funnel_monthly": "mart_credit_funnel_monthly",
    "portfolio_monthly": "mart_portfolio_monthly",
    "delinquency_monthly": "mart_delinquency_monthly",
    "vintage_cohorts": "mart_vintage_cohorts",
    "roll_rates": "mart_roll_rates",
    "cure_and_redefault": "mart_cure_and_redefault",
    "collections_performance": "mart_collections_performance",
    "writeoff_recovery": "mart_writeoff_recovery",
    "scenario_comparison": "mart_scenario_comparison",
    "macro_stress_pre_post": "mart_macro_stress_pre_post",
}


class InsightsGenerationError(Exception):
    """Raised when insights cannot be generated from the given analysis output."""


@dataclass(frozen=True)
class Insight:
    insight_id: str
    question_id: str | None
    title: str
    statement_en: str
    statement_pt: str
    statement_type: StatementType
    baseline_value: float | None
    compared_value: float | None
    delta: float | None
    unit: str
    period: str
    grain: str
    filters: dict[str, Any]
    scenario: str | None
    seed_or_seeds: str
    sample_size: int | None
    sample_classification: str | None
    dbt_model: str | None
    query_function: str
    evidence_table: str
    figure: str | None
    build_id: str
    warehouse_fingerprint: str
    analysis_id: str
    provenance_classification: str
    limitation: str
    validation_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "insight_id": self.insight_id,
            "question_id": self.question_id,
            "title": self.title,
            "statement": {"en": self.statement_en, "pt_br": self.statement_pt},
            "statement_type": self.statement_type,
            "baseline_value": self.baseline_value,
            "compared_value": self.compared_value,
            "delta": self.delta,
            "unit": self.unit,
            "period": self.period,
            "grain": self.grain,
            "filters": self.filters,
            "scenario": self.scenario,
            "seed_or_seeds": self.seed_or_seeds,
            "sample_size": self.sample_size,
            "sample_classification": self.sample_classification,
            "dbt_model": self.dbt_model,
            "query": self.query_function,
            "evidence_table": self.evidence_table,
            "figure": self.figure,
            "build_id": self.build_id,
            "warehouse_fingerprint": self.warehouse_fingerprint,
            "analysis_id": self.analysis_id,
            "provenance_classification": self.provenance_classification,
            "limitation": self.limitation,
            "validation_status": self.validation_status,
        }


def is_executive_ready(insight: Insight) -> bool:
    """False for `unsupported`/`hypothesis` statements (Phase 7 gate D)
    and for any insight whose sample is `insufficient` (Phase 7 gate B) -
    the dashboard/report "key findings" surfacing must filter on this."""
    if insight.statement_type in _NOT_EXECUTIVE_READY:
        return False
    return insight.sample_classification != "insufficient"


def _read_table(tables_dir: Path, name: str) -> pd.DataFrame:
    path = tables_dir / f"{name}.csv"
    if not path.is_file():
        raise InsightsGenerationError(f"Required evidence table '{path}' does not exist.")
    return pd.read_csv(path)


def _period_from_dates(series: pd.Series) -> str:
    dates = pd.to_datetime(series, errors="coerce").dropna()
    if dates.empty:
        return "n/a"
    return f"{dates.min().date()} to {dates.max().date()}"


def generate_insights(
    output_dir: Path,
    *,
    robustness_report_path: Path | None = None,
    repo_root: Path | None = None,
) -> list[Insight]:
    """Generates the Phase 7 gate D insights registry from a real,
    already-validated `credlens analysis run` output directory. Every
    numeric value is read directly from
    `output_dir/tables/*.csv`/`manifest.json` - never hand-typed."""
    repo_root = repo_root or Path.cwd()
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.is_file():
        raise InsightsGenerationError(
            f"No analysis manifest at '{manifest_path}' - run `credlens analysis run` first."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    build_id = manifest["build_id"]
    analysis_id = manifest["analysis_id"]
    warehouse_fingerprint = manifest["warehouse_fingerprint"]
    suite_id = manifest.get("suite_id") or "n/a"
    tables_dir = output_dir / "tables"

    insights: list[Insight] = []
    seq = 0

    def _next_id(slug: str) -> str:
        nonlocal seq
        seq += 1
        return f"INS-{slug}-{seq:03d}"

    def _common(
        *,
        table_name: str,
        scenario: str | None,
        figure: str | None = None,
    ) -> dict[str, Any]:
        provenance = get_table_provenance(table_name)
        return {
            "build_id": build_id,
            "warehouse_fingerprint": warehouse_fingerprint,
            "analysis_id": analysis_id,
            "evidence_table": f"reports/portfolio_analysis/tables/{table_name}.csv",
            "figure": (f"reports/portfolio_analysis/figures/{figure}.png" if figure else None),
            "dbt_model": _TABLE_TO_DBT_MODEL.get(table_name),
            "query_function": f"credlens.analysis.metrics.{table_name}",
            "provenance_classification": provenance.category,
            "scenario": scenario,
            "seed_or_seeds": suite_id,
        }

    # --- Funnel (baseline) --------------------------------------------------
    funnel = _read_table(tables_dir, "funnel_monthly")
    base_funnel = funnel[funnel["scenario"] == "baseline"]
    if not base_funnel.empty:
        submitted = float(base_funnel["applications_submitted"].sum())
        decisioned = float(base_funnel["decisioned_applications"].sum())
        approved = float(base_funnel["approved_count"].sum())
        booked = float(base_funnel["booked_count"].sum())
        approval_rate = approved / decisioned if decisioned else None
        booking_rate = booked / approved if approved else None
        sample_class = classify_sample_size(int(decisioned))
        insights.append(
            Insight(
                insight_id=_next_id("FUN"),
                question_id="FUN-01",
                title="Baseline credit funnel",
                statement_en=(
                    f"In the baseline scenario, {int(submitted):,} applications were submitted, "
                    f"{int(decisioned):,} were decisioned, {int(approved):,} were approved "
                    f"({approval_rate:.2%} approval rate) and {int(booked):,} were booked "
                    f"({booking_rate:.2%} of approved)."
                    if approval_rate is not None and booking_rate is not None
                    else "Baseline funnel counts are recorded, but rates could not be computed "
                    "(zero decisioned or approved applications)."
                ),
                statement_pt=(
                    f"No cenario baseline, {int(submitted):,} solicitacoes foram enviadas, "
                    f"{int(decisioned):,} foram decididas, {int(approved):,} foram aprovadas "
                    f"({approval_rate:.2%} de taxa de aprovacao) e {int(booked):,} foram "
                    f"contratadas ({booking_rate:.2%} das aprovadas)."
                    if approval_rate is not None and booking_rate is not None
                    else "As contagens do funil baseline foram registradas, mas as taxas nao "
                    "puderam ser calculadas (zero solicitacoes decididas ou aprovadas)."
                ),
                statement_type="observed_synthetic_result",
                baseline_value=submitted,
                compared_value=booked,
                delta=booked - submitted,
                unit="count",
                period=_period_from_dates(base_funnel["submitted_month"]),
                grain="run_id x submitted_month x channel, summed for the whole suite period",
                filters={"scenario": "baseline"},
                sample_size=int(decisioned),
                sample_classification=sample_class,
                limitation=(
                    "Counts only; no revenue/cost weighting of the funnel stages "
                    "(see analysis/questions.yml FUN-01)."
                ),
                validation_status="validated",
                **_common(table_name="funnel_monthly", scenario="baseline", figure="credit_funnel"),
            )
        )

    # --- Outstanding balance (baseline) --------------------------------------
    portfolio = _read_table(tables_dir, "portfolio_monthly")
    base_portfolio = portfolio[portfolio["scenario"] == "baseline"].sort_values("snapshot_date")
    if not base_portfolio.empty:
        first_balance = float(base_portfolio["outstanding_balance"].iloc[0])
        last_balance = float(base_portfolio["outstanding_balance"].iloc[-1])
        active_contracts_final = int(base_portfolio["active_contracts"].iloc[-1])
        insights.append(
            Insight(
                insight_id=_next_id("COMP"),
                question_id="COMP-01",
                title="Baseline outstanding balance trajectory",
                statement_en=(
                    f"Baseline outstanding balance moved from {first_balance:,.2f} to "
                    f"{last_balance:,.2f} synthetic monetary units across the observed period "
                    f"({active_contracts_final:,} active contracts at the final snapshot)."
                ),
                statement_pt=(
                    f"O saldo em aberto do baseline foi de {first_balance:,.2f} para "
                    f"{last_balance:,.2f} unidades monetarias sinteticas ao longo do periodo "
                    f"observado ({active_contracts_final:,} contratos ativos no ultimo snapshot)."
                ),
                statement_type="observed_synthetic_result",
                baseline_value=first_balance,
                compared_value=last_balance,
                delta=last_balance - first_balance,
                unit="synthetic_monetary_units",
                period=_period_from_dates(base_portfolio["snapshot_date"]),
                grain="run_id x snapshot_date (STOCK)",
                filters={"scenario": "baseline"},
                sample_size=active_contracts_final,
                sample_classification=classify_sample_size(active_contracts_final),
                limitation=(
                    "Synthetic monetary units; no real BRL purchasing-power context "
                    "(see analysis/questions.yml COMP-01)."
                ),
                validation_status="validated",
                **_common(
                    table_name="portfolio_monthly",
                    scenario="baseline",
                    figure="outstanding_balance_over_time",
                ),
            )
        )

    # --- PAR30/60/90 (baseline, final snapshot) ------------------------------
    delinquency = _read_table(tables_dir, "delinquency_monthly")
    base_delinquency = delinquency[delinquency["scenario"] == "baseline"].sort_values(
        "snapshot_date"
    )
    if not base_delinquency.empty:
        final_row = base_delinquency.iloc[-1]
        total_contracts_final = int(final_row["total_contracts"])
        for par_label, par_col, count_col in (
            ("PAR30", "par30", "contracts_30plus"),
            ("PAR60", "par60", "contracts_60plus"),
            ("PAR90", "par90", "contracts_90plus"),
        ):
            par_value = float(final_row[par_col])
            insights.append(
                Insight(
                    insight_id=_next_id("DEL"),
                    question_id="DEL-01",
                    title=f"Baseline {par_label} at final snapshot",
                    statement_en=(
                        f"At the final observed snapshot, baseline {par_label} was "
                        f"{par_value:.2%} of outstanding balance "
                        f"({int(final_row[count_col]):,} of {total_contracts_final:,} contracts)."
                    ),
                    statement_pt=(
                        f"No ultimo snapshot observado, o {par_label} do baseline foi de "
                        f"{par_value:.2%} do saldo em aberto "
                        f"({int(final_row[count_col]):,} de {total_contracts_final:,} contratos)."
                    ),
                    statement_type="observed_synthetic_result",
                    baseline_value=None,
                    compared_value=par_value,
                    delta=None,
                    unit="fraction_of_balance",
                    period=str(final_row["snapshot_date"]),
                    grain="run_id x snapshot_date",
                    filters={"scenario": "baseline"},
                    sample_size=total_contracts_final,
                    sample_classification=classify_sample_size(total_contracts_final),
                    limitation=(
                        "Balance-weighted rate at one snapshot date, not a trend "
                        "(see analysis/questions.yml DEL-01)."
                    ),
                    validation_status="validated",
                    **_common(
                        table_name="delinquency_monthly", scenario="baseline", figure="par_curves"
                    ),
                )
            )

        avg_cure_rate = float(base_delinquency["cure_rate"].mean())
        insights.append(
            Insight(
                insight_id=_next_id("CUR"),
                question_id="CUR-01",
                title="Baseline cure rate (period average)",
                statement_en=(
                    f"Baseline's monthly cure rate averaged {avg_cure_rate:.2%} across the "
                    "observed period (mart_delinquency_monthly.cure_rate)."
                ),
                statement_pt=(
                    f"A taxa de cura mensal do baseline foi, em media, {avg_cure_rate:.2%} ao "
                    "longo do periodo observado (mart_delinquency_monthly.cure_rate)."
                ),
                statement_type="observed_synthetic_result",
                baseline_value=None,
                compared_value=avg_cure_rate,
                delta=None,
                unit="fraction",
                period=_period_from_dates(base_delinquency["snapshot_date"]),
                grain="run_id x snapshot_date, averaged across months",
                filters={"scenario": "baseline"},
                sample_size=total_contracts_final,
                sample_classification=classify_sample_size(total_contracts_final),
                limitation=(
                    "A simple mean of a monthly rate, not weighted by delinquent population."
                ),
                validation_status="validated",
                **_common(
                    table_name="delinquency_monthly",
                    scenario="baseline",
                    figure="cure_and_relapse",
                ),
            )
        )

    # --- Roll rate (baseline, whole period) ----------------------------------
    roll_rates = _read_table(tables_dir, "roll_rates")
    base_roll = roll_rates[roll_rates["scenario"] == "baseline"]
    from_current = base_roll[base_roll["from_bucket"] == "current"]
    if not from_current.empty:
        total_from_current = float(from_current["contract_count"].sum())
        stayed_current = float(
            from_current.loc[from_current["to_bucket"] == "current", "contract_count"].sum()
        )
        roll_forward_rate = (
            1.0 - (stayed_current / total_from_current) if total_from_current else None
        )
        if roll_forward_rate is not None:
            insights.append(
                Insight(
                    insight_id=_next_id("VIN"),
                    question_id="VIN-01",
                    title="Baseline roll-forward rate from current",
                    statement_en=(
                        f"Of {int(total_from_current):,} current-bucket contract-months "
                        f"observed in baseline, {roll_forward_rate:.2%} rolled forward into a "
                        "delinquent bucket the following month (mart_roll_rates)."
                    ),
                    statement_pt=(
                        f"Dos {int(total_from_current):,} contrato-meses no bucket 'current' "
                        f"observados no baseline, {roll_forward_rate:.2%} avancaram para um "
                        "bucket de atraso no mes seguinte (mart_roll_rates)."
                    ),
                    statement_type="observed_synthetic_result",
                    baseline_value=None,
                    compared_value=roll_forward_rate,
                    delta=None,
                    unit="fraction",
                    period="Whole suite period",
                    grain="run_id x snapshot_date x from_bucket x to_bucket, summed",
                    filters={"scenario": "baseline", "from_bucket": "current"},
                    sample_size=int(total_from_current),
                    sample_classification=classify_sample_size(int(total_from_current)),
                    limitation="Aggregated across the whole period, not month-by-month.",
                    validation_status="validated",
                    **_common(
                        table_name="roll_rates", scenario="baseline", figure="roll_rate_heatmap"
                    ),
                )
            )

    # --- Vintage (baseline, most mature cohort) ------------------------------
    vintage = _read_table(tables_dir, "vintage_cohorts")
    base_vintage = vintage[vintage["scenario"] == "baseline"]
    if not base_vintage.empty:
        most_mature_mob = int(base_vintage["max_mob_observed_for_cohort"].min())
        at_mob = base_vintage[base_vintage["months_on_book"] == most_mature_mob]
        at_mob = at_mob[at_mob["contracts_observed"] > 0]
        if not at_mob.empty:
            contracts_observed = float(at_mob["contracts_observed"].sum())
            contracts_90plus = float(at_mob["contracts_90plus"].sum())
            rate_90plus = contracts_90plus / contracts_observed if contracts_observed else None
            if rate_90plus is not None:
                insights.append(
                    Insight(
                        insight_id=_next_id("VIN"),
                        question_id="VIN-01",
                        title=f"Baseline vintage 90+ incidence at MOB {most_mature_mob}",
                        statement_en=(
                            f"Across cohorts that have all reached month-on-book "
                            f"{most_mature_mob}, {rate_90plus:.2%} of "
                            f"{int(contracts_observed):,} contracts were 90+ DPD "
                            "(mart_vintage_cohorts, comparable-MOB only)."
                        ),
                        statement_pt=(
                            f"Entre as coortes que atingiram o mes-na-carteira "
                            f"{most_mature_mob}, {rate_90plus:.2%} de "
                            f"{int(contracts_observed):,} contratos estavam com 90+ dias de "
                            "atraso (mart_vintage_cohorts, apenas MOB comparavel)."
                        ),
                        statement_type="observed_synthetic_result",
                        baseline_value=None,
                        compared_value=rate_90plus,
                        delta=None,
                        unit="fraction",
                        period=f"months_on_book = {most_mature_mob}",
                        grain="run_id x vintage_month x months_on_book",
                        filters={"scenario": "baseline", "months_on_book": most_mature_mob},
                        sample_size=int(contracts_observed),
                        sample_classification=classify_sample_size(int(contracts_observed)),
                        limitation=(
                            "Only cohorts that have reached this MOB are compared "
                            "(analysis/questions.yml VIN-01/VIN-02)."
                        ),
                        validation_status="validated",
                        **_common(
                            table_name="vintage_cohorts",
                            scenario="baseline",
                            figure="vintage_curves",
                        ),
                    )
                )

    # --- Redefault rate (baseline) --------------------------------------------
    cure_redefault = _read_table(tables_dir, "cure_and_redefault")
    base_cure = cure_redefault[cure_redefault["scenario"] == "baseline"]
    if not base_cure.empty:
        n_ever_cured = int(base_cure["was_ever_cured"].sum())
        n_redefaulted = int(base_cure["redefaulted"].sum())
        redefault_rate = n_redefaulted / n_ever_cured if n_ever_cured else None
        insights.append(
            Insight(
                insight_id=_next_id("CUR"),
                question_id="CUR-02",
                title="Baseline redefault (relapse) rate",
                statement_en=(
                    f"Of {n_ever_cured:,} baseline contracts that ever cured, {n_redefaulted:,} "
                    f"later redefaulted ({redefault_rate:.2%})."
                    if redefault_rate is not None
                    else "No baseline contracts were ever cured in this build - redefault rate "
                    "is not computable."
                ),
                statement_pt=(
                    f"Dos {n_ever_cured:,} contratos do baseline que ja curaram, {n_redefaulted:,} "
                    f"posteriormente reincidiram ({redefault_rate:.2%})."
                    if redefault_rate is not None
                    else "Nenhum contrato do baseline curou neste build - a taxa de reincidencia "
                    "nao e computavel."
                ),
                statement_type="observed_synthetic_result",
                baseline_value=float(n_ever_cured),
                compared_value=float(n_redefaulted),
                delta=float(n_redefaulted - n_ever_cured),
                unit="count_and_fraction",
                period="Whole suite period",
                grain="run_id x contract_key",
                filters={"scenario": "baseline"},
                sample_size=n_ever_cured,
                sample_classification=classify_sample_size(n_ever_cured),
                limitation=(
                    "warehouse/analyses/redefault_rate.sql is the canonical aggregate query."
                ),
                validation_status="validated" if redefault_rate is not None else "unsupported",
                **_common(
                    table_name="cure_and_redefault",
                    scenario="baseline",
                    figure="cure_and_relapse",
                ),
            )
        )

    # --- Write-off and recovery (baseline) -----------------------------------
    writeoff = _read_table(tables_dir, "writeoff_recovery")
    base_writeoff = writeoff[writeoff["scenario"] == "baseline"]
    if not base_writeoff.empty:
        total_write_off = float(base_writeoff["total_write_off_amount"].sum())
        total_recovery = float(base_writeoff["total_recovery_amount"].sum())
        write_off_count = int(base_writeoff["write_off_count"].sum())
        recovery_rate = total_recovery / total_write_off if total_write_off else None
        insights.append(
            Insight(
                insight_id=_next_id("COL"),
                question_id="COL-01",
                title="Baseline write-off total",
                statement_en=(
                    f"Baseline wrote off {total_write_off:,.2f} synthetic monetary units across "
                    f"{write_off_count:,} contracts."
                ),
                statement_pt=(
                    f"O baseline baixou {total_write_off:,.2f} unidades monetarias sinteticas "
                    f"em {write_off_count:,} contratos."
                ),
                statement_type="observed_synthetic_result",
                baseline_value=None,
                compared_value=total_write_off,
                delta=None,
                unit="synthetic_monetary_units",
                period="Whole suite period",
                grain="run_id x write_off_month, summed",
                filters={"scenario": "baseline"},
                sample_size=write_off_count,
                sample_classification=classify_sample_size(write_off_count),
                limitation=(
                    "No LGD/EAD modeling - a DGP configuration outcome, not a real loss estimate."
                ),
                validation_status="validated",
                **_common(
                    table_name="writeoff_recovery",
                    scenario="baseline",
                    figure="writeoff_and_recovery",
                ),
            )
        )
        insights.append(
            Insight(
                insight_id=_next_id("COL"),
                question_id="COL-01",
                title="Baseline recovery total and rate",
                statement_en=(
                    f"Baseline recovered {total_recovery:,.2f} synthetic monetary units against "
                    f"{total_write_off:,.2f} written off "
                    f"({recovery_rate:.2%} recovery rate)."
                    if recovery_rate is not None
                    else "Baseline recorded no write-offs in this build - recovery rate is not "
                    "computable."
                ),
                statement_pt=(
                    f"O baseline recuperou {total_recovery:,.2f} unidades monetarias sinteticas "
                    f"contra {total_write_off:,.2f} baixados "
                    f"({recovery_rate:.2%} de taxa de recuperacao)."
                    if recovery_rate is not None
                    else "O baseline nao registrou baixas neste build - a taxa de recuperacao "
                    "nao e computavel."
                ),
                statement_type="observed_synthetic_result",
                baseline_value=total_write_off,
                compared_value=total_recovery,
                delta=total_recovery - total_write_off,
                unit="synthetic_monetary_units",
                period="Whole suite period",
                grain="run_id x write_off_month, summed",
                filters={"scenario": "baseline"},
                sample_size=write_off_count,
                sample_classification=classify_sample_size(write_off_count),
                limitation=(
                    "recovery_rate reflects the DGP's own configured recovery-probability rule, "
                    "not a real collections operation's performance."
                ),
                validation_status="validated" if recovery_rate is not None else "unsupported",
                **_common(
                    table_name="writeoff_recovery",
                    scenario="baseline",
                    figure="writeoff_and_recovery",
                ),
            )
        )

    # --- Scenario comparisons: policy_expansion / policy_tightening / collections_change ---
    scenario_cmp = _read_table(tables_dir, "scenario_comparison")
    for scenario_name, question_id in (
        ("policy_expansion", "FUN-03"),
        ("policy_tightening", "FUN-03"),
        ("collections_change", "SCN-01"),
    ):
        row = scenario_cmp[scenario_cmp["scenario"] == scenario_name]
        if row.empty:
            continue
        r = row.iloc[0]
        insights.append(
            Insight(
                insight_id=_next_id("SCN"),
                question_id=question_id,
                title=f"{scenario_name} vs. baseline approval rate",
                statement_en=(
                    f"{scenario_name}'s approval rate was {float(r['approval_rate']):.2%} vs. "
                    f"{float(r['baseline_approval_rate']):.2%} for baseline "
                    f"(delta {float(r['approval_rate_delta_abs']):+.2%})."
                ),
                statement_pt=(
                    f"A taxa de aprovacao de {scenario_name} foi {float(r['approval_rate']):.2%} "
                    f"vs. {float(r['baseline_approval_rate']):.2%} do baseline "
                    f"(delta {float(r['approval_rate_delta_abs']):+.2%})."
                ),
                statement_type="scenario_comparison",
                baseline_value=float(r["baseline_approval_rate"]),
                compared_value=float(r["approval_rate"]),
                delta=float(r["approval_rate_delta_abs"]),
                unit="fraction",
                period="Whole run",
                grain="suite_id x scenario",
                filters={"scenario": scenario_name},
                sample_size=None,
                sample_classification=None,
                limitation=(
                    "Single suite/seed - see the multi-seed robustness insights for "
                    "run-to-run variability."
                ),
                validation_status="validated",
                **_common(
                    table_name="scenario_comparison",
                    scenario=scenario_name,
                    figure="policy_scenario_comparison",
                ),
            )
        )

    # --- Macroeconomic stress: pre/post shock --------------------------------
    macro_pp = _read_table(tables_dir, "macro_stress_pre_post")
    for period_name in ("pre_shock", "post_shock"):
        row = macro_pp[macro_pp["period"] == period_name]
        if row.empty:
            continue
        r = row.iloc[0]
        insights.append(
            Insight(
                insight_id=_next_id("SCN"),
                question_id="SCN-02",
                title=f"Macro stress PAR90 delta - {period_name}",
                statement_en=(
                    f"During the {period_name.replace('_', '-')} period, macroeconomic_stress's "
                    f"PAR90 was {float(r['stress_par90']):.4%} vs. baseline's "
                    f"{float(r['baseline_par90']):.4%} (delta {float(r['par90_delta_abs']):+.4%})."
                ),
                statement_pt=(
                    f"No periodo {period_name.replace('_', '-')}, o PAR90 de "
                    f"macroeconomic_stress foi {float(r['stress_par90']):.4%} vs. "
                    f"{float(r['baseline_par90']):.4%} do baseline "
                    f"(delta {float(r['par90_delta_abs']):+.4%})."
                ),
                statement_type="scenario_comparison",
                baseline_value=float(r["baseline_par90"]),
                compared_value=float(r["stress_par90"]),
                delta=float(r["par90_delta_abs"]),
                unit="fraction_of_balance",
                period=period_name,
                grain="suite_id x period",
                filters={"scenario": "macroeconomic_stress", "period": period_name},
                sample_size=None,
                sample_classification=None,
                limitation=(
                    "Pre-shock delta is expected to be ~0 by CRN design "
                    "(warehouse/tests/assert_pre_shock_period_identical_across_scenarios.sql); "
                    "single suite/seed."
                ),
                validation_status="validated",
                **_common(
                    table_name="macro_stress_pre_post",
                    scenario="macroeconomic_stress",
                    figure="macro_stress_pre_post",
                ),
            )
        )

    # --- Multi-seed robustness (Phase 7 gate A) ------------------------------
    if robustness_report_path is not None and robustness_report_path.is_file():
        robustness = json.loads(robustness_report_path.read_text(encoding="utf-8"))
        for scenario_name, scenario_result in robustness.get("scenarios", {}).items():
            expected_metric = next(
                (
                    name
                    for name, m in scenario_result["metrics"].items()
                    if m.get("expected_direction") is not None
                ),
                None,
            )
            if expected_metric is None:
                continue
            m = scenario_result["metrics"][expected_metric]
            seeds = scenario_result["seeds"]
            fraction = m["fraction_in_expected_direction"]
            insights.append(
                Insight(
                    insight_id=_next_id("ROBUST"),
                    question_id="SCN-03",
                    title=f"{scenario_name} multi-seed robustness ({expected_metric})",
                    statement_en=(
                        f"Across {len(seeds)} seeds ({min(seeds)}-{max(seeds)}) at smoke scale, "
                        f"{scenario_name}'s {expected_metric} moved in the expected direction "
                        f"({m['expected_direction']}) in "
                        f"{fraction:.0%} of seeds (mean delta {m['mean']:+.4f}, "
                        f"stdev {m['stdev']:.4f}, {m['inversions']} inversion(s))."
                    ),
                    statement_pt=(
                        f"Em {len(seeds)} seeds ({min(seeds)}-{max(seeds)}) na escala smoke, "
                        f"{expected_metric} de {scenario_name} moveu-se na direcao esperada "
                        f"({m['expected_direction']}) em "
                        f"{fraction:.0%} das seeds (delta medio {m['mean']:+.4f}, "
                        f"desvio padrao {m['stdev']:.4f}, {m['inversions']} inversao(oes))."
                    ),
                    statement_type="analytical_inference",
                    baseline_value=None,
                    compared_value=fraction,
                    delta=m["mean"],
                    unit="fraction_of_seeds",
                    period=f"{min(seeds)}-{max(seeds)}",
                    grain="scenario x seed, smoke scale",
                    filters={"scenario": scenario_name, "scale": "smoke"},
                    scenario=scenario_name,
                    seed_or_seeds=f"{min(seeds)}-{max(seeds)} (n={len(seeds)})",
                    sample_size=len(seeds),
                    sample_classification=None,
                    dbt_model=None,
                    query_function="credlens.analysis.robustness.full_robustness_sweep",
                    evidence_table="reports/synthetic_validation/multiseed_robustness.json",
                    figure=None,
                    build_id=build_id,
                    warehouse_fingerprint=warehouse_fingerprint,
                    analysis_id=analysis_id,
                    provenance_classification="synthetic_scenario",
                    limitation=(
                        "Variability across synthetic DGP runs / Variabilidade entre execucoes "
                        "do DGP sintetico - NEVER a statistical confidence interval. Generation-"
                        "layer metric, not a rebuilt warehouse per seed."
                    ),
                    validation_status="validated",
                )
            )

    # --- Public benchmark description (Phase 7 gate C/D) ---------------------
    try:
        from credlens.analysis.benchmark import profile_public_sources
        from credlens.analysis.data_provenance import classify_source_id
    except ImportError:
        profile_public_sources = None  # type: ignore[assignment]

    if profile_public_sources is not None:
        for profile in profile_public_sources(repo_root=repo_root):
            category = classify_source_id(profile.source_id)
            insights.append(
                Insight(
                    insight_id=_next_id("BMK"),
                    question_id="SCN-04",
                    title=f"Public source profile: {profile.source_id}",
                    statement_en=(
                        f"{profile.source_id} ({profile.context.get('population', 'n/a')}, "
                        f"{profile.context.get('period', 'n/a')}) has {profile.num_rows:,} rows "
                        f"and {profile.num_columns} columns - a real public source, structurally "
                        "profiled and kept separate from the synthetic portfolio."
                    ),
                    statement_pt=(
                        f"{profile.source_id} ({profile.context.get('population', 'n/a')}, "
                        f"{profile.context.get('period', 'n/a')}) tem {profile.num_rows:,} "
                        f"linhas e {profile.num_columns} colunas - uma fonte publica real, "
                        "perfilada estruturalmente e mantida separada da carteira sintetica."
                    ),
                    statement_type="public_benchmark_description",
                    baseline_value=None,
                    compared_value=float(profile.num_rows),
                    delta=None,
                    unit="count",
                    period=str(profile.context.get("period", "n/a")),
                    grain="source_id",
                    filters={"source_id": profile.source_id},
                    scenario=None,
                    seed_or_seeds="n/a",
                    sample_size=profile.num_rows,
                    sample_classification=None,
                    dbt_model=None,
                    query_function="credlens.analysis.benchmark.profile_public_sources",
                    evidence_table="n/a (profiled directly from data/raw/ at analysis time)",
                    figure="public_benchmark_overview",
                    build_id=build_id,
                    warehouse_fingerprint=warehouse_fingerprint,
                    analysis_id=analysis_id,
                    provenance_classification=category,
                    limitation=(
                        "Structural profile only - never merged with the synthetic portfolio, "
                        "never treated as a CredLens result."
                    ),
                    validation_status="validated",
                )
            )

    # --- Explicit unsupported example (Phase 7 gate D section 7.1) ----------
    insights.append(
        Insight(
            insight_id=_next_id("OOS"),
            question_id=None,
            title="Portfolio profitability - not computed",
            statement_en=(
                "Revenue, cost of funds, contribution margin, and expected loss (PD x EAD x LGD) "
                "are NOT computed anywhere in this project - see docs/roadmap.md phase 9. Any "
                "profitability claim would be unsupported by current data."
            ),
            statement_pt=(
                "Receita, custo de captacao, margem de contribuicao e perda esperada "
                "(PD x EAD x LGD) NAO sao calculados em nenhum lugar deste projeto - ver "
                "docs/roadmap.md fase 9. Qualquer alegacao de rentabilidade seria sem "
                "sustentacao nos dados atuais."
            ),
            statement_type="unsupported",
            baseline_value=None,
            compared_value=None,
            delta=None,
            unit="n/a",
            period="n/a",
            grain="n/a",
            filters={},
            scenario=None,
            seed_or_seeds="n/a",
            sample_size=None,
            sample_classification=None,
            dbt_model=None,
            query_function="n/a",
            evidence_table="n/a",
            figure=None,
            build_id=build_id,
            warehouse_fingerprint=warehouse_fingerprint,
            analysis_id=analysis_id,
            provenance_classification="synthetic_operational",
            limitation="Explicitly out of scope through Phase 7 - see docs/roadmap.md.",
            validation_status="unsupported",
        )
    )

    return insights


# Fields that are legitimate EXECUTION METADATA, not reproducible
# CONTENT (Phase 7 gate E: "Separe: metadata de execucao; conteudo
# reproduzivel"). `analysis_id` embeds a fresh timestamp on every
# `credlens analysis run` invocation by design (see
# credlens.analysis.runner.run_analysis) - two runs against the exact
# same build produce byte-identical insight VALUES but a different
# analysis_id, so it must be excluded from the reproducibility fingerprint
# even though it is kept, per-insight, in the written registry itself for
# traceability (Phase 7 gate D requires it as a field).
_METADATA_ONLY_FIELDS = frozenset({"analysis_id"})


def content_fingerprint(insights: list[Insight]) -> str:
    """A reproducibility-focused hash of the insights list's decision-
    relevant content, excluding `_METADATA_ONLY_FIELDS`. This is what
    `credlens analysis reproduce` should compare for the insights
    registry - never the raw file's byte hash, which would spuriously
    differ across two otherwise-identical runs solely because
    `analysis_id` changed."""
    normalized = [
        {k: v for k, v in insight.to_dict().items() if k not in _METADATA_ONLY_FIELDS}
        for insight in insights
    ]
    payload = json.dumps(normalized, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_insights_registry(insights: list[Insight], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "generated_by": "credlens.analysis.insights.generate_insights",
        "count": len(insights),
        "insights": [i.to_dict() for i in insights],
    }
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
