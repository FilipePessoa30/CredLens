"""Chart generation (Phase 6 section 15) - every figure here is produced
by code from real query results (`credlens.analysis.metrics`), never
edited by hand. Uses the Okabe-Ito palette (colorblind-accessible,
https://jfly.uni-koeln.de/color/), labeled axes/units, a "Synthetic data"
watermark on every figure, no 3D, no truncated/misleading axes, no
decorative chart junk. PNG output (matplotlib's default DPI is legible at
report scale); each function returns the Path it wrote.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless - this package never opens an interactive window
import matplotlib.pyplot as plt
import pandas as pd

# Okabe-Ito: black, orange, sky blue, bluish green, yellow, blue,
# vermillion, reddish purple - distinguishable under the three common
# forms of color vision deficiency.
_PALETTE = {
    "black": "#000000",
    "orange": "#E69F00",
    "sky_blue": "#56B4E9",
    "bluish_green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "vermillion": "#D55E00",
    "reddish_purple": "#CC79A7",
}
_SCENARIO_COLORS = {
    "baseline": _PALETTE["black"],
    "policy_expansion": _PALETTE["bluish_green"],
    "policy_tightening": _PALETTE["vermillion"],
    "macroeconomic_stress": _PALETTE["blue"],
    "collections_change": _PALETTE["orange"],
}


def _watermark(fig: Any) -> None:
    fig.text(
        0.99,
        0.01,
        "Synthetic data - CredLens DGP, not a real institution",
        ha="right",
        va="bottom",
        fontsize=7,
        color="#666666",
        style="italic",
    )


def _new_fig(figsize: tuple[float, float] = (9, 5)) -> tuple[Any, Any]:
    fig, ax = plt.subplots(figsize=figsize)
    return fig, ax


def _save(fig: Any, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _watermark(fig)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def credit_funnel(df: pd.DataFrame, output_path: Path) -> Path:
    """Funnel: submitted -> decisioned -> approved -> booked, by
    scenario, summed across the whole period."""
    agg = df.groupby("scenario")[
        ["applications_submitted", "decisioned_applications", "approved_count", "booked_count"]
    ].sum()
    stages = ["applications_submitted", "decisioned_applications", "approved_count", "booked_count"]
    stage_labels = ["Submitted", "Decisioned", "Approved", "Booked"]

    fig, ax = _new_fig((9, 5.5))
    x = range(len(stages))
    for scenario, row in agg.iterrows():
        color = _SCENARIO_COLORS.get(str(scenario), _PALETTE["black"])
        ax.plot(x, [row[s] for s in stages], marker="o", label=str(scenario), color=color)
    ax.set_xticks(list(x))
    ax.set_xticklabels(stage_labels)
    ax.set_ylabel("Applications (count)")
    ax.set_title("Credit Funnel by Scenario (synthetic)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    return _save(fig, output_path)


def outstanding_balance_over_time(df: pd.DataFrame, output_path: Path) -> Path:
    """Outstanding balance (STOCK) over time, one line per scenario."""
    fig, ax = _new_fig()
    for scenario, group in df.groupby("scenario"):
        g = group.sort_values("snapshot_date")
        color = _SCENARIO_COLORS.get(str(scenario), _PALETTE["black"])
        ax.plot(g["snapshot_date"], g["outstanding_balance"], label=str(scenario), color=color)
    ax.set_xlabel("Snapshot date")
    ax.set_ylabel("Outstanding balance (BRL, synthetic)")
    ax.set_title("Outstanding Balance Over Time by Scenario (synthetic)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    return _save(fig, output_path)


def par_curves(df: pd.DataFrame, output_path: Path, scenario: str = "baseline") -> Path:
    """PAR30/60/90 over time, for one scenario (default baseline) -
    balance-weighted delinquency severity."""
    g = df[df["scenario"] == scenario].sort_values("snapshot_date")
    fig, ax = _new_fig()
    ax.plot(g["snapshot_date"], g["par30"], label="PAR30", color=_PALETTE["yellow"])
    ax.plot(g["snapshot_date"], g["par60"], label="PAR60", color=_PALETTE["orange"])
    ax.plot(g["snapshot_date"], g["par90"], label="PAR90", color=_PALETTE["vermillion"])
    ax.set_xlabel("Snapshot date")
    ax.set_ylabel("Portfolio at Risk (fraction of balance)")
    ax.set_title(f"PAR30/60/90 Over Time - {scenario} (synthetic)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    return _save(fig, output_path)


def roll_rate_heatmap(
    df: pd.DataFrame, output_path: Path, scenario_run_id: str | None = None
) -> Path:
    """DPD bucket transition heatmap (from_bucket -> to_bucket), summed
    across all observed months for one run."""
    bucket_order = ["current", "1-29", "30-59", "60-89", "90+"]
    data = df if scenario_run_id is None else df[df["run_id"] == scenario_run_id]
    pivot = (
        data.groupby(["from_bucket", "to_bucket"])["contract_count"]
        .sum()
        .unstack(fill_value=0)
        .reindex(index=bucket_order, columns=bucket_order, fill_value=0)
    )
    matrix = pivot.to_numpy()
    fig, ax = _new_fig((7, 6))
    im = ax.imshow(matrix, cmap="Blues")
    ax.set_xticks(range(len(bucket_order)))
    ax.set_xticklabels(bucket_order)
    ax.set_yticks(range(len(bucket_order)))
    ax.set_yticklabels(bucket_order)
    ax.set_xlabel("To bucket (this month)")
    ax.set_ylabel("From bucket (prior month)")
    ax.set_title("DPD Bucket Roll-Rate Matrix (synthetic)")
    for i in range(len(bucket_order)):
        for j in range(len(bucket_order)):
            ax.text(j, i, int(matrix[i, j]), ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, label="Contract count")
    return _save(fig, output_path)


def vintage_curves(df: pd.DataFrame, output_path: Path, scenario: str = "baseline") -> Path:
    """90+ incidence by months-on-book, one line per origination cohort -
    only plotted up to each cohort's own max_mob_observed_for_cohort."""
    g = df[df["scenario"] == scenario]
    fig, ax = _new_fig()
    for vintage_month, cohort in g.groupby("vintage_month"):
        cohort = cohort.sort_values("months_on_book")
        cohort = cohort[cohort["contracts_observed"] > 0]
        rate = cohort["contracts_90plus"] / cohort["contracts_observed"].replace(0, pd.NA)
        ax.plot(cohort["months_on_book"], rate, marker=".", label=str(vintage_month)[:7], alpha=0.8)
    ax.set_xlabel("Months on book (MOB)")
    ax.set_ylabel("90+ DPD incidence (fraction of cohort)")
    ax.set_title(f"Vintage Curves by MOB - {scenario} (synthetic)")
    ax.legend(fontsize=6, ncol=2)
    ax.grid(alpha=0.3)
    return _save(fig, output_path)


def cure_and_relapse(df: pd.DataFrame, output_path: Path) -> Path:
    """Cure vs. redefault (relapse) counts, by scenario - among
    contracts ever cured, how many later relapsed."""
    agg = df.groupby("scenario").agg(
        was_ever_cured=("was_ever_cured", "sum"), redefaulted=("redefaulted", "sum")
    )
    agg["cured_only"] = agg["was_ever_cured"] - agg["redefaulted"]
    fig, ax = _new_fig()
    x = range(len(agg))
    ax.bar(x, agg["cured_only"], label="Cured, no relapse", color=_PALETTE["bluish_green"])
    ax.bar(
        x,
        agg["redefaulted"],
        bottom=agg["cured_only"],
        label="Cured then relapsed",
        color=_PALETTE["vermillion"],
    )
    ax.set_xticks(list(x))
    ax.set_xticklabels(list(agg.index), rotation=20, ha="right")
    ax.set_ylabel("Contracts (count)")
    ax.set_title("Cure and Relapse (Redefault) by Scenario (synthetic)")
    ax.legend(fontsize=8)
    return _save(fig, output_path)


def writeoff_and_recovery(df: pd.DataFrame, output_path: Path) -> Path:
    """Write-off amount vs. recovered amount, by scenario, summed across
    the period - the recovery bar is always <= the write-off bar."""
    agg = df.groupby("scenario")[["total_write_off_amount", "total_recovery_amount"]].sum()
    fig, ax = _new_fig()
    x = range(len(agg))
    ax.bar(
        [i - 0.2 for i in x],
        agg["total_write_off_amount"],
        width=0.4,
        label="Written off",
        color=_PALETTE["vermillion"],
    )
    ax.bar(
        [i + 0.2 for i in x],
        agg["total_recovery_amount"],
        width=0.4,
        label="Recovered",
        color=_PALETTE["bluish_green"],
    )
    ax.set_xticks(list(x))
    ax.set_xticklabels(list(agg.index), rotation=20, ha="right")
    ax.set_ylabel("Amount (BRL, synthetic)")
    ax.set_title("Write-off and Recovery by Scenario (synthetic)")
    ax.legend(fontsize=8)
    return _save(fig, output_path)


def policy_scenario_comparison(df: pd.DataFrame, output_path: Path) -> Path:
    """Baseline vs. scenario approval_rate/dpd90_rate/write_off_count -
    one panel per metric, scenarios on the x-axis."""
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.5))
    metrics_ = [
        ("approval_rate", "baseline_approval_rate", "Approval rate"),
        ("dpd90_rate_final_month", "baseline_dpd90_rate", "DPD90+ rate (final month)"),
        ("write_off_count", "baseline_write_off_count", "Write-off count"),
    ]
    for ax, (scenario_col, baseline_col, title) in zip(axes, metrics_, strict=True):
        x = range(len(df))
        ax.bar(
            [i - 0.2 for i in x],
            df[baseline_col],
            width=0.4,
            label="Baseline",
            color=_PALETTE["black"],
        )
        ax.bar(
            [i + 0.2 for i in x],
            df[scenario_col],
            width=0.4,
            label="Scenario",
            color=_PALETTE["blue"],
        )
        ax.set_xticks(list(x))
        ax.set_xticklabels(df["scenario"], rotation=30, ha="right", fontsize=7)
        ax.set_title(title, fontsize=10)
        ax.legend(fontsize=7)
    fig.suptitle("Baseline vs. Scenario Comparison (synthetic)")
    return _save(fig, output_path)


def macro_stress_pre_post_chart(df: pd.DataFrame, output_path: Path) -> Path:
    """Baseline vs. stress PAR90, split by pre-shock/post-shock period -
    should show near-zero delta pre-shock and real divergence post-shock."""
    order = ["pre_shock", "post_shock"]
    g = df.set_index("period").reindex(order)
    fig, ax = _new_fig()
    x = range(len(order))
    ax.bar(
        [i - 0.2 for i in x],
        g["baseline_par90"],
        width=0.4,
        label="Baseline",
        color=_PALETTE["black"],
    )
    ax.bar(
        [i + 0.2 for i in x],
        g["stress_par90"],
        width=0.4,
        label="Stress",
        color=_PALETTE["vermillion"],
    )
    ax.set_xticks(list(x))
    ax.set_xticklabels(["Pre-shock", "Post-shock"])
    ax.set_ylabel("Average PAR90")
    ax.set_title("Macro Stress: PAR90 Pre- vs. Post-Shock (synthetic)")
    ax.legend(fontsize=8)
    return _save(fig, output_path)


def multiseed_stability(summary: dict[str, Any], output_path: Path) -> Path:
    """Mean delta +/- stdev across seeds, one bar per metric - explicitly
    labeled 'simulation variability', never a confidence interval."""
    metrics_ = summary.get("metric_summaries", {})
    names = list(metrics_.keys())
    means = [metrics_[n]["mean_delta"] for n in names]
    stdevs = [metrics_[n]["stdev_delta"] for n in names]

    fig, ax = _new_fig()
    x = range(len(names))
    ax.bar(x, means, yerr=stdevs, capsize=4, color=_PALETTE["sky_blue"])
    ax.axhline(0, color=_PALETTE["black"], linewidth=0.8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(names, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("Mean delta (scenario - baseline)")
    n = len(summary.get("seeds", []))
    ax.set_title(f"Simulation Variability Across {n} Seeds (synthetic - not a statistical CI)")
    return _save(fig, output_path)


def quality_provenance_scorecard(manifest_summary: dict[str, Any], output_path: Path) -> Path:
    """A compact scorecard: build/dbt test pass rate, reconciliation
    pass rate, source count, fingerprint presence - a glance-able "is this
    analysis trustworthy" panel."""
    rows = [
        ("dbt tests passed", manifest_summary.get("dbt_tests_passed", 0)),
        ("dbt tests failed", manifest_summary.get("dbt_tests_failed", 0)),
        ("reconciliation checks passed", manifest_summary.get("reconciliation_passed", 0)),
        ("reconciliation checks failed", manifest_summary.get("reconciliation_failed", 0)),
        ("source runs included", manifest_summary.get("n_sources", 0)),
    ]
    fig, ax = _new_fig((7, 4))
    labels = [r[0] for r in rows]
    values = [r[1] for r in rows]
    colors = [
        _PALETTE["bluish_green"] if "failed" not in label or value == 0 else _PALETTE["vermillion"]
        for label, value in zip(labels, values, strict=True)
    ]
    ax.barh(labels, values, color=colors)
    ax.set_xlabel("Count")
    ax.set_title("Build Quality / Provenance Scorecard (synthetic)")
    for i, v in enumerate(values):
        ax.text(v, i, f" {v}", va="center", fontsize=9)
    return _save(fig, output_path)


def public_benchmark_overview(profiles: list[dict[str, Any]], output_path: Path) -> Path:
    """Row counts of the public benchmark sources, kept visually and
    numerically separate from every synthetic-operational chart above."""
    labels = [p["source_id"] for p in profiles]
    values = [p["num_rows"] for p in profiles]
    fig, ax = _new_fig((7, 4))
    ax.bar(labels, values, color=_PALETTE["reddish_purple"])
    ax.set_ylabel("Rows")
    ax.set_title("Public Benchmark Sources - Row Counts (REAL public data, not synthetic)")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
    return _save(fig, output_path)
