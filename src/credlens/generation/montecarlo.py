"""Monte Carlo comparison across multiple seeds (Phase 4B section 13).

Runs a baseline+scenario suite once per seed and aggregates each
comparable metric's delta (scenario - baseline) across seeds: mean,
standard deviation, quantiles, and the fraction of seeds where the delta
landed in the scenario's documented expected direction. This is a
technical Monte Carlo summary over THIS generator's own synthetic draws -
explicitly NOT a confidence interval over any real population (see
docs/counterfactual_scenarios.md and
credlens.generation.validation's "statistical validation is not a
business finding" posture, which this module shares).
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path

from credlens.generation.suite import generate_suite

# The one or two metrics each scenario is EXPECTED (by this synthetic DGP's
# own documented design, not by any real-world claim) to move in a
# consistent direction - see docs/counterfactual_scenarios.md section
# "targets and tolerances" for the reasoning behind each entry.
EXPECTED_DIRECTIONS: dict[str, dict[str, str]] = {
    "policy_expansion": {"approval_rate": "increase"},
    "policy_tightening": {"approval_rate": "decrease"},
    "macroeconomic_stress": {"dpd90_plus_rate": "increase"},
    "collections_change": {"cure_rate": "increase"},
}


@dataclass(frozen=True)
class MonteCarloMetricSummary:
    metric: str
    expected_direction: str | None
    deltas: list[float]
    mean_delta: float
    stdev_delta: float
    quantiles: dict[str, float]
    fraction_in_expected_direction: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "metric": self.metric,
            "expected_direction": self.expected_direction,
            "n_seeds": len(self.deltas),
            "mean_delta": round(self.mean_delta, 6),
            "stdev_delta": round(self.stdev_delta, 6),
            "quantiles": {k: round(v, 6) for k, v in self.quantiles.items()},
            "fraction_in_expected_direction": (
                round(self.fraction_in_expected_direction, 6)
                if self.fraction_in_expected_direction is not None
                else None
            ),
        }


@dataclass(frozen=True)
class MonteCarloResult:
    scenario: str
    scale: str
    seeds: list[int]
    metric_summaries: dict[str, MonteCarloMetricSummary]
    contract_failures: list[int]

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "scale": self.scale,
            "seeds": self.seeds,
            "n_seeds": len(self.seeds),
            "contract_failures": self.contract_failures,
            "metrics": {name: s.to_dict() for name, s in self.metric_summaries.items()},
        }


def _quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    sorted_values = sorted(values)
    n = len(sorted_values)

    def q(p: float) -> float:
        idx = min(n - 1, max(0, round(p * (n - 1))))
        return sorted_values[idx]

    return {"p10": q(0.10), "p50": q(0.50), "p90": q(0.90)}


def run_monte_carlo(
    *, scenario: str, scale_name: str, seeds: list[int], force: bool = True
) -> MonteCarloResult:
    if not seeds:
        raise ValueError("run_monte_carlo requires at least 1 seed.")

    per_metric_deltas: dict[str, list[float]] = {}
    contract_failures: list[int] = []

    for seed in seeds:
        outcome = generate_suite(
            scale_name=scale_name, seed=seed, force=force, scenarios=(scenario,)
        )
        report = outcome.manifest["scenarios"][scenario]  # type: ignore[index]
        for comparison in report["metric_comparisons"]:
            per_metric_deltas.setdefault(comparison["metric"], []).append(comparison["delta"])

        baseline_status = outcome.outcomes["baseline"].status
        scenario_status = outcome.outcomes[scenario].status
        if baseline_status != "completed" or scenario_status != "completed":
            contract_failures.append(seed)

    expected = EXPECTED_DIRECTIONS.get(scenario, {})
    summaries: dict[str, MonteCarloMetricSummary] = {}
    for metric, deltas in per_metric_deltas.items():
        direction = expected.get(metric)
        fraction_in_direction: float | None = None
        if direction == "increase":
            fraction_in_direction = sum(1 for d in deltas if d > 0) / len(deltas)
        elif direction == "decrease":
            fraction_in_direction = sum(1 for d in deltas if d < 0) / len(deltas)
        summaries[metric] = MonteCarloMetricSummary(
            metric=metric,
            expected_direction=direction,
            deltas=deltas,
            mean_delta=statistics.fmean(deltas),
            stdev_delta=statistics.pstdev(deltas) if len(deltas) > 1 else 0.0,
            quantiles=_quantiles(deltas),
            fraction_in_expected_direction=fraction_in_direction,
        )

    return MonteCarloResult(
        scenario=scenario,
        scale=scale_name,
        seeds=list(seeds),
        metric_summaries=summaries,
        contract_failures=contract_failures,
    )


def write_monte_carlo_report(path: Path, result: MonteCarloResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
