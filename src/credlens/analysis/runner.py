"""Orchestrates one full analysis run (Phase 6): validates the build,
runs every SQL-first metric query, generates figures, writes tables,
computes provenance, and writes bilingual reports. `credlens analysis
run` is a thin CLI wrapper around `run_analysis()` - all the logic lives
here so it is independently testable.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from credlens.analysis import benchmark, charts, metrics, reporting, scenarios
from credlens.analysis.provenance import (
    AnalysisManifest,
    finalize,
    new_manifest,
    record_figure,
    record_table,
)
from credlens.analysis.validation import validate_build_for_analysis
from credlens.warehouse.reconciliation import run_reconciliation


class AnalysisRunError(Exception):
    """Raised when an analysis run cannot proceed or fails."""


@dataclass(frozen=True)
class AnalysisResult:
    analysis_id: str
    output_dir: Path
    manifest_path: Path
    executive_summary_en: Path
    executive_summary_pt: Path
    technical_report_en: Path
    technical_report_pt: Path
    manifest: AnalysisManifest


def run_analysis(
    build_id: str,
    output_dir: Path,
    *,
    include_benchmark: bool = True,
    include_multiseed: bool = False,
    multiseed_seeds: int = 5,
    multiseed_scenario: str = "macroeconomic_stress",
    multiseed_scale: str = "smoke",
) -> AnalysisResult:
    build = validate_build_for_analysis(build_id)
    if build.suite_id is None:
        raise AnalysisRunError(
            f"Build '{build_id}' was built from a single run_id, not a suite_id - "
            "credlens analysis run needs a suite (baseline + scenarios) to compare."
        )
    suite_id = build.suite_id

    analysis_id = f"ANALYSIS_{build_id}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    parameters = {
        "include_benchmark": include_benchmark,
        "include_multiseed": include_multiseed,
        "multiseed_seeds": multiseed_seeds,
        "multiseed_scenario": multiseed_scenario,
        "multiseed_scale": multiseed_scale,
    }
    manifest = new_manifest(build, analysis_id, parameters)

    tables_dir = output_dir / "tables"
    figures_dir = output_dir / "figures"
    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    with metrics.connect(Path(build.db_path)) as conn:
        query_results: dict[str, pd.DataFrame] = {
            "funnel_monthly": metrics.funnel_monthly(conn, suite_id),
            "portfolio_monthly": metrics.portfolio_monthly(conn, suite_id),
            "delinquency_monthly": metrics.delinquency_monthly(conn, suite_id),
            "vintage_cohorts": metrics.vintage_cohorts(conn, suite_id),
            "roll_rates": metrics.roll_rates(conn, suite_id),
            "cure_and_redefault": metrics.cure_and_redefault(conn, suite_id),
            "collections_performance": metrics.collections_performance(conn, suite_id),
            "writeoff_recovery": metrics.writeoff_recovery(conn, suite_id),
            "scenario_comparison": metrics.scenario_comparison(conn, suite_id),
            "macro_stress_pre_post": metrics.macro_stress_pre_post(conn, suite_id),
            "funnel_by_channel_and_scenario": metrics.funnel_by_channel_and_scenario(
                conn, suite_id
            ),
            "portfolio_by_region_and_channel": metrics.portfolio_by_region_and_channel(
                conn, suite_id
            ),
            "policy_version_comparison": metrics.policy_version_comparison(conn, suite_id),
        }

        composition: dict[str, dict[str, object]] = {}
        for scenario_name in ("policy_expansion", "policy_tightening"):
            with contextlib.suppress(ValueError):
                composition[scenario_name] = scenarios.composition_vs_performance(
                    conn, suite_id, scenario_name
                ).to_dict()

    for name, df in query_results.items():
        path = tables_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        record_table(manifest, name, path)
        manifest.queries_executed.append(name)

    figure_specs: list[tuple[str, Callable[[], Path]]] = [
        (
            "credit_funnel",
            lambda: charts.credit_funnel(
                query_results["funnel_monthly"], figures_dir / "credit_funnel.png"
            ),
        ),
        (
            "outstanding_balance_over_time",
            lambda: charts.outstanding_balance_over_time(
                query_results["portfolio_monthly"],
                figures_dir / "outstanding_balance_over_time.png",
            ),
        ),
        (
            "par_curves",
            lambda: charts.par_curves(
                query_results["delinquency_monthly"], figures_dir / "par_curves.png"
            ),
        ),
        (
            "roll_rate_heatmap",
            lambda: charts.roll_rate_heatmap(
                query_results["roll_rates"], figures_dir / "roll_rate_heatmap.png"
            ),
        ),
        (
            "vintage_curves",
            lambda: charts.vintage_curves(
                query_results["vintage_cohorts"], figures_dir / "vintage_curves.png"
            ),
        ),
        (
            "cure_and_relapse",
            lambda: charts.cure_and_relapse(
                query_results["cure_and_redefault"], figures_dir / "cure_and_relapse.png"
            ),
        ),
        (
            "writeoff_and_recovery",
            lambda: charts.writeoff_and_recovery(
                query_results["writeoff_recovery"], figures_dir / "writeoff_and_recovery.png"
            ),
        ),
        (
            "policy_scenario_comparison",
            lambda: charts.policy_scenario_comparison(
                query_results["scenario_comparison"], figures_dir / "policy_scenario_comparison.png"
            ),
        ),
        (
            "macro_stress_pre_post",
            lambda: charts.macro_stress_pre_post_chart(
                query_results["macro_stress_pre_post"], figures_dir / "macro_stress_pre_post.png"
            ),
        ),
    ]
    figures_written_paths: dict[str, Path] = {}
    for name, build_fn in figure_specs:
        try:
            path = build_fn()
            record_figure(manifest, name, path)
            figures_written_paths[name] = path
        except Exception as exc:
            manifest.warnings.append(f"Figure '{name}' failed: {type(exc).__name__}: {exc}")

    multiseed_summary = None
    if include_multiseed:
        from credlens.analysis.multiseed import robustness_across_seeds

        result = robustness_across_seeds(multiseed_scenario, multiseed_scale, multiseed_seeds)
        multiseed_summary = result.to_dict()
        try:
            path = charts.multiseed_stability(
                multiseed_summary, figures_dir / "multiseed_stability.png"
            )
            record_figure(manifest, "multiseed_stability", path)
        except Exception as exc:
            manifest.warnings.append(
                f"Figure 'multiseed_stability' failed: {type(exc).__name__}: {exc}"
            )

    benchmark_profiles: list[dict[str, object]] = []
    if include_benchmark:
        benchmark_profiles = [p.to_dict() for p in benchmark.profile_public_sources()]
        if benchmark_profiles:
            try:
                path = charts.public_benchmark_overview(
                    benchmark_profiles, figures_dir / "public_benchmark_overview.png"
                )
                record_figure(manifest, "public_benchmark_overview", path)
            except Exception as exc:
                manifest.warnings.append(
                    f"Figure 'public_benchmark_overview' failed: {type(exc).__name__}: {exc}"
                )

    reconciliation_results = [
        r.to_dict() for r in run_reconciliation(Path(build.db_path), build.sources)
    ]

    quality_summary = {
        "dbt_tests_passed": build.test_results.get("passed", 0),
        "dbt_tests_failed": build.test_results.get("failed", 0),
        "reconciliation_passed": sum(1 for r in reconciliation_results if r["passed"]),
        "reconciliation_failed": sum(1 for r in reconciliation_results if not r["passed"]),
        "n_sources": len(build.sources),
    }
    try:
        path = charts.quality_provenance_scorecard(
            quality_summary, figures_dir / "quality_provenance_scorecard.png"
        )
        record_figure(manifest, "quality_provenance_scorecard", path)
    except Exception as exc:
        manifest.warnings.append(
            f"Figure 'quality_provenance_scorecard' failed: {type(exc).__name__}: {exc}"
        )

    executive_en = reporting.build_executive_summary(
        lang="en",
        suite_id=suite_id,
        build_id=build_id,
        fingerprint=build.analytical_fingerprint,
        scenario_cmp=query_results["scenario_comparison"],
        macro_pp=query_results["macro_stress_pre_post"],
        composition=composition,
        writeoff_recovery_totals=query_results["writeoff_recovery"],
    )
    executive_pt = reporting.build_executive_summary(
        lang="pt-BR",
        suite_id=suite_id,
        build_id=build_id,
        fingerprint=build.analytical_fingerprint,
        scenario_cmp=query_results["scenario_comparison"],
        macro_pp=query_results["macro_stress_pre_post"],
        composition=composition,
        writeoff_recovery_totals=query_results["writeoff_recovery"],
    )
    technical_en = reporting.build_technical_report(
        lang="en",
        build_id=build_id,
        suite_id=suite_id,
        fingerprint=build.analytical_fingerprint,
        manifest=manifest.to_dict(),
        scenario_cmp=query_results["scenario_comparison"],
        macro_pp=query_results["macro_stress_pre_post"],
        composition=composition,
        multiseed_summary=multiseed_summary,
        benchmark_profiles=benchmark_profiles,
        reconciliation_results=reconciliation_results,
        dbt_test_results=build.test_results,
        figures_written=manifest.figures_written,
    )
    technical_pt = reporting.build_technical_report(
        lang="pt-BR",
        build_id=build_id,
        suite_id=suite_id,
        fingerprint=build.analytical_fingerprint,
        manifest=manifest.to_dict(),
        scenario_cmp=query_results["scenario_comparison"],
        macro_pp=query_results["macro_stress_pre_post"],
        composition=composition,
        multiseed_summary=multiseed_summary,
        benchmark_profiles=benchmark_profiles,
        reconciliation_results=reconciliation_results,
        dbt_test_results=build.test_results,
        figures_written=manifest.figures_written,
    )

    executive_summary_en_path = output_dir / "executive_summary.md"
    executive_summary_pt_path = output_dir / "executive_summary.pt-BR.md"
    technical_report_en_path = output_dir / "technical_report.md"
    technical_report_pt_path = output_dir / "technical_report.pt-BR.md"
    executive_summary_en_path.write_text(executive_en, encoding="utf-8")
    executive_summary_pt_path.write_text(executive_pt, encoding="utf-8")
    technical_report_en_path.write_text(technical_en, encoding="utf-8")
    technical_report_pt_path.write_text(technical_pt, encoding="utf-8")

    any_reconciliation_failed = any(not r["passed"] for r in reconciliation_results)
    finalize(
        manifest, status="success" if not any_reconciliation_failed else "completed_with_warnings"
    )
    manifest_path = output_dir / "manifest.json"
    manifest.write(manifest_path)

    return AnalysisResult(
        analysis_id=analysis_id,
        output_dir=output_dir,
        manifest_path=manifest_path,
        executive_summary_en=executive_summary_en_path,
        executive_summary_pt=executive_summary_pt_path,
        technical_report_en=technical_report_en_path,
        technical_report_pt=technical_report_pt_path,
        manifest=manifest,
    )
