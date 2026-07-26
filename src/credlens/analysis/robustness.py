"""Multi-scenario, multi-seed robustness sweep (Phase 7 gate A).

Phase 6 (`credlens.analysis.multiseed`) only ever swept
`macroeconomic_stress` across seeds. This module runs the SAME
mechanism - `credlens.generation.suite.generate_suite` +
`credlens.generation.comparison` (both already tested, generation-layer,
fast at `smoke` scale) - for all four comparable CRN scenarios:
`policy_expansion`, `policy_tightening`, `macroeconomic_stress`,
`collections_change`, using the identical seed sequence for every
scenario so results are directly comparable across scenarios.

Every seed generates its OWN baseline + scenario pair sharing common
random numbers (see docs/common_random_numbers.md) - "seeds paired with
their baseline" is therefore automatic, not a separate bookkeeping step.

This operates at the GENERATION layer (parquet outputs), not by
rebuilding a dbt warehouse per seed - rebuilding the full warehouse 40
times (10 seeds x 4 scenarios) would be far more expensive than the
`smoke`-scale generation itself and would duplicate business logic
already tested in `warehouse/models/marts/*.sql`. Richer,
balance-weighted, warehouse-layer metrics (true PAR, roll rates,
redefault via `mart_cure_and_redefault`) are computed once per suite (see
`credlens.analysis.metrics`/`scenarios`), not swept across seeds - that
scope boundary is stated explicitly here and in the final report, never
hidden.

Every result is labeled, in both languages, as simulation/run-to-run
variability of this synthetic DGP - NEVER a statistical confidence
interval over any real institution or population (see
docs/assumptions_and_limitations.md and
credlens.analysis.multiseed's identical posture for the single-scenario
case this module generalizes).
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from credlens.generation.comparison import compare_metrics, compute_metrics
from credlens.generation.config import config_path_for_scenario, load_generation_config
from credlens.generation.montecarlo import EXPECTED_DIRECTIONS
from credlens.generation.suite import generate_suite

VARIABILITY_LABEL_EN = "Variability across synthetic DGP runs"
VARIABILITY_LABEL_PT = "Variabilidade entre execucoes do DGP sintetico"

# All four comparable CRN scenarios (Phase 7 gate A) - baseline is
# excluded, it has nothing to compare itself against.
ROBUSTNESS_SCENARIOS: tuple[str, ...] = (
    "policy_expansion",
    "policy_tightening",
    "macroeconomic_stress",
    "collections_change",
)

# Chosen to never collide with any official demo run/suite/seed (Phase 6
# gate B) or with Phase 6's own multiseed default (970_001) or its test
# seed (960_501) - see credlens.analysis.multiseed and
# tests/test_analysis_multiseed.py.
DEFAULT_START_SEED = 5_970_001

_DIRECTION_TOLERANCE = 1e-9


def _observed_direction(delta: float, tolerance: float = _DIRECTION_TOLERANCE) -> str:
    if delta > tolerance:
        return "increase"
    if delta < -tolerance:
        return "decrease"
    return "no_change"


def _quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    sorted_values = sorted(values)
    n = len(sorted_values)

    def q(p: float) -> float:
        idx = min(n - 1, max(0, round(p * (n - 1))))
        return sorted_values[idx]

    return {"p10": q(0.10), "p50": q(0.50), "p90": q(0.90)}


@dataclass(frozen=True)
class MetricRobustness:
    metric: str
    scenario: str
    seeds: list[int]
    baseline_values: list[float]
    scenario_values: list[float]
    deltas: list[float]
    relative_deltas: list[float | None]
    expected_direction: str | None
    observed_directions: list[str]
    fraction_in_expected_direction: float | None
    inversions: int
    mean: float
    median: float
    stdev: float
    quantiles: dict[str, float]
    minimum: float
    maximum: float
    n_seeds: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "scenario": self.scenario,
            "seeds": self.seeds,
            "baseline_values": [round(v, 6) for v in self.baseline_values],
            "scenario_values": [round(v, 6) for v in self.scenario_values],
            "delta_absolute_per_seed": [round(v, 6) for v in self.deltas],
            "delta_relative_per_seed": [
                (round(v, 6) if v is not None else None) for v in self.relative_deltas
            ],
            "expected_direction": self.expected_direction,
            "observed_direction_per_seed": self.observed_directions,
            "fraction_in_expected_direction": (
                round(self.fraction_in_expected_direction, 6)
                if self.fraction_in_expected_direction is not None
                else None
            ),
            "inversions": self.inversions,
            "mean": round(self.mean, 6),
            "median": round(self.median, 6),
            "stdev": round(self.stdev, 6),
            "quantiles": {k: round(v, 6) for k, v in self.quantiles.items()},
            "minimum": round(self.minimum, 6),
            "maximum": round(self.maximum, 6),
            "n_seeds": self.n_seeds,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class ScenarioRobustnessResult:
    scenario: str
    scale: str
    seeds: list[int]
    metrics: dict[str, MetricRobustness]
    pre_shock_equality: dict[str, Any] | None
    contract_failures: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "scale": self.scale,
            "seeds": self.seeds,
            "n_seeds": len(self.seeds),
            "metrics": {name: m.to_dict() for name, m in self.metrics.items()},
            "pre_shock_equality": self.pre_shock_equality,
            "contract_failures": self.contract_failures,
            "label_en": VARIABILITY_LABEL_EN,
            "label_pt_br": VARIABILITY_LABEL_PT,
        }


def _pre_shock_equality_row(
    seed: int, baseline_dir: Path, scenario_dir: Path, shock_date: Any
) -> dict[str, Any]:
    """A generation-layer, aggregate corroboration of the pre-shock
    identity guarantee macroeconomic_stress's own dbt test enforces at
    row level (warehouse/tests/assert_pre_shock_period_identical_across_
    scenarios.sql) - here checked once per seed, directly against the
    parquet both runs share via common random numbers before shock_date."""
    baseline_path = baseline_dir / "account_monthly_snapshots.parquet"
    scenario_path = scenario_dir / "account_monthly_snapshots.parquet"
    if not baseline_path.is_file() or not scenario_path.is_file():
        return {
            "seed": seed,
            "n_snapshots_pre_shock_baseline": 0,
            "n_snapshots_pre_shock_scenario": 0,
            "dpd30_plus_rate_baseline": None,
            "dpd30_plus_rate_scenario": None,
            "delta": None,
            "identical": False,
        }
    baseline_snap = pd.read_parquet(baseline_path)
    scenario_snap = pd.read_parquet(scenario_path)
    shock_ts = pd.Timestamp(shock_date)
    b_pre = baseline_snap[pd.to_datetime(baseline_snap["snapshot_date"]) < shock_ts]
    s_pre = scenario_snap[pd.to_datetime(scenario_snap["snapshot_date"]) < shock_ts]

    def _dpd30_rate(df: pd.DataFrame) -> float:
        if df.empty:
            return 0.0
        return float((pd.to_numeric(df["dpd"], errors="coerce") >= 30).mean())

    b_rate = _dpd30_rate(b_pre)
    s_rate = _dpd30_rate(s_pre)
    delta = s_rate - b_rate
    return {
        "seed": seed,
        "n_snapshots_pre_shock_baseline": len(b_pre),
        "n_snapshots_pre_shock_scenario": len(s_pre),
        "dpd30_plus_rate_baseline": b_rate,
        "dpd30_plus_rate_scenario": s_rate,
        "delta": delta,
        "identical": abs(delta) < _DIRECTION_TOLERANCE,
    }


def _summarize_pre_shock(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    n_identical = sum(1 for r in rows if r["identical"])
    deltas = [r["delta"] for r in rows if r["delta"] is not None]
    return {
        "seeds_checked": [r["seed"] for r in rows],
        "n_seeds": n,
        "n_identical": n_identical,
        "fraction_identical": (n_identical / n) if n else None,
        "max_absolute_delta": max((abs(d) for d in deltas), default=0.0),
        "rows": rows,
        "label": "pre_shock_equality_check_generation_layer_aggregate",
    }


def run_scenario_robustness(
    scenario: str,
    scale_name: str,
    seeds: list[int],
    *,
    output_dirs: tuple[Path, Path] | None = None,
    manifest_dir: Path | None = None,
    force: bool = True,
) -> ScenarioRobustnessResult:
    """Runs `scenario` vs. baseline across every seed in `seeds` (each
    seed's baseline+scenario pair sharing common random numbers) and
    aggregates every metric `credlens.generation.comparison` computes."""
    per_metric_baseline: dict[str, list[float]] = {}
    per_metric_scenario: dict[str, list[float]] = {}
    per_metric_delta: dict[str, list[float]] = {}
    contract_failures: list[int] = []
    pre_shock_rows: list[dict[str, Any]] = []

    shock_date = None
    if scenario == "macroeconomic_stress":
        shock_config = load_generation_config(config_path_for_scenario("macroeconomic_stress"))
        if shock_config.macro_shock is not None:
            shock_date = shock_config.macro_shock.shock_date

    for seed in seeds:
        outcome = generate_suite(
            scale_name=scale_name,
            seed=seed,
            force=force,
            scenarios=(scenario,),
            output_dirs=output_dirs,
            manifest_dir=manifest_dir,
        )
        baseline_outcome = outcome.outcomes["baseline"]
        scenario_outcome = outcome.outcomes[scenario]
        baseline_dir = baseline_outcome.operational_dir / "operational"
        scenario_dir = scenario_outcome.operational_dir / "operational"

        baseline_metrics = compute_metrics(
            baseline_outcome.generation_run_id, baseline_dir, baseline_outcome.truth_dir
        )
        scenario_metrics = compute_metrics(
            scenario_outcome.generation_run_id, scenario_dir, scenario_outcome.truth_dir
        )
        for comparison in compare_metrics(baseline_metrics, scenario_metrics):
            per_metric_baseline.setdefault(comparison.metric, []).append(comparison.baseline_value)
            per_metric_scenario.setdefault(comparison.metric, []).append(comparison.candidate_value)
            per_metric_delta.setdefault(comparison.metric, []).append(comparison.delta)

        if baseline_outcome.status != "completed" or scenario_outcome.status != "completed":
            contract_failures.append(seed)

        if scenario == "macroeconomic_stress" and shock_date is not None:
            pre_shock_rows.append(
                _pre_shock_equality_row(seed, baseline_dir, scenario_dir, shock_date)
            )

    expected = EXPECTED_DIRECTIONS.get(scenario, {})
    metrics: dict[str, MetricRobustness] = {}
    for metric, deltas in per_metric_delta.items():
        direction = expected.get(metric)
        observed = [_observed_direction(d) for d in deltas]
        fraction: float | None = None
        inversions = 0
        warnings: list[str] = []
        if direction is not None:
            matches = [(d > 0) if direction == "increase" else (d < 0) for d in deltas]
            fraction = sum(matches) / len(matches)
            inversions = sum(1 for m in matches if not m)
            if fraction < 1.0:
                warnings.append(
                    f"{inversions} of {len(deltas)} seed(s) moved opposite the expected "
                    f"direction ({direction}) for '{metric}'."
                )
        baseline_vals = per_metric_baseline[metric]
        relative_deltas = [
            (d / b if b not in (0, 0.0) else None)
            for d, b in zip(deltas, baseline_vals, strict=True)
        ]
        metrics[metric] = MetricRobustness(
            metric=metric,
            scenario=scenario,
            seeds=list(seeds),
            baseline_values=baseline_vals,
            scenario_values=per_metric_scenario[metric],
            deltas=deltas,
            relative_deltas=relative_deltas,
            expected_direction=direction,
            observed_directions=observed,
            fraction_in_expected_direction=fraction,
            inversions=inversions,
            mean=statistics.fmean(deltas),
            median=statistics.median(deltas),
            stdev=statistics.pstdev(deltas) if len(deltas) > 1 else 0.0,
            quantiles=_quantiles(deltas),
            minimum=min(deltas),
            maximum=max(deltas),
            n_seeds=len(deltas),
            warnings=warnings,
        )

    pre_shock_summary = (
        _summarize_pre_shock(pre_shock_rows) if scenario == "macroeconomic_stress" else None
    )

    return ScenarioRobustnessResult(
        scenario=scenario,
        scale=scale_name,
        seeds=list(seeds),
        metrics=metrics,
        pre_shock_equality=pre_shock_summary,
        contract_failures=contract_failures,
    )


def full_robustness_sweep(
    *,
    scale_name: str = "smoke",
    n_seeds: int = 10,
    start_seed: int = DEFAULT_START_SEED,
    scenarios: tuple[str, ...] = ROBUSTNESS_SCENARIOS,
    output_dirs: tuple[Path, Path] | None = None,
    manifest_dir: Path | None = None,
) -> dict[str, ScenarioRobustnessResult]:
    """Phase 7 gate A: runs every scenario in `scenarios` across the SAME
    seed sequence [start_seed, start_seed + n_seeds), so results are
    directly comparable across scenarios."""
    seeds = [start_seed + i for i in range(n_seeds)]
    return {
        scenario: run_scenario_robustness(
            scenario,
            scale_name,
            seeds,
            output_dirs=output_dirs,
            manifest_dir=manifest_dir,
        )
        for scenario in scenarios
    }


def write_robustness_report(path: Path, results: dict[str, ScenarioRobustnessResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "label_en": VARIABILITY_LABEL_EN,
        "label_pt_br": VARIABILITY_LABEL_PT,
        "scenarios": {name: r.to_dict() for name, r in results.items()},
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
