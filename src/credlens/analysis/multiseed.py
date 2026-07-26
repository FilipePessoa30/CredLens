"""Multi-seed robustness (Phase 6 section 13): a single seed cannot
characterize how stable the DGP's own scenario effects are. Reuses
`credlens.generation.montecarlo.run_monte_carlo` (Phase 4B) - this module
adds nothing new to HOW seeds are compared, only summarizes/labels the
result for the analysis report, and is explicit that this measures
**simulation variability** (how much a synthetic DGP's own output moves
across seeds), never a real institution's statistical confidence
interval - see docs/assumptions_and_limitations.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from credlens.generation.montecarlo import MonteCarloResult, run_monte_carlo


@dataclass(frozen=True)
class RobustnessSummary:
    scenario: str
    scale: str
    seeds: list[int]
    metric_summaries: dict[str, dict[str, Any]]
    # Seeds (baseline or scenario side) that failed contract validation.
    contract_failures: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "scale": self.scale,
            "seeds": self.seeds,
            "metric_summaries": self.metric_summaries,
            "contract_failures": self.contract_failures,
            "label": "simulation_variability_across_synthetic_dgp_seeds",
        }


def _summarize(result: MonteCarloResult) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, summary in result.metric_summaries.items():
        out[name] = {
            "mean_delta": summary.mean_delta,
            "stdev_delta": summary.stdev_delta,
            "min_delta": min(summary.deltas) if summary.deltas else None,
            "max_delta": max(summary.deltas) if summary.deltas else None,
            "n_seeds": len(summary.deltas),
            "expected_direction": summary.expected_direction,
            "fraction_in_expected_direction": summary.fraction_in_expected_direction,
            "any_inversion": (
                summary.fraction_in_expected_direction is not None
                and summary.fraction_in_expected_direction < 1.0
            ),
        }
    return out


def robustness_across_seeds(
    scenario: str, scale_name: str, n_seeds: int, start_seed: int = 970_001
) -> RobustnessSummary:
    """Runs the scenario vs. baseline across `n_seeds` seeds starting at
    `start_seed` (never the CLI's own default 2026 - Phase 6 gate B: this
    generates real data, so it must never collide with an official
    demonstration seed) at `scale_name` (smoke for routine use - never
    portfolio for a repeated multi-seed sweep, per Phase 6 section 13)."""
    seeds = [start_seed + i for i in range(n_seeds)]
    result = run_monte_carlo(scenario=scenario, scale_name=scale_name, seeds=seeds)
    return RobustnessSummary(
        scenario=scenario,
        scale=scale_name,
        seeds=seeds,
        metric_summaries=_summarize(result),
        contract_failures=result.contract_failures,
    )
