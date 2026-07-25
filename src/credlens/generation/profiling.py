"""`credlens synthetic profile` support (Phase 4B section 2/14).

THREE passes, deliberately not one or two: a plain `time.perf_counter` pass
with NO instrumentation at all for the accurate duration, a separate
`tracemalloc` pass for peak memory, and a separate `cProfile` pass for a
top-N hotspot breakdown. Two real, measured overheads justify keeping these
apart rather than combining any of them:

- `cProfile`'s own per-call instrumentation was found, during this phase's
  optimization work, to inflate wall time by roughly 4x on this workload
  (many small Python-level calls in the ledger simulation).
- `tracemalloc` was found, while building THIS command, to inflate wall time
  by roughly 8x on the same workload (millions of small allocations - a
  `Decimal` per installment component, a dict per row - and tracemalloc's
  overhead scales with allocation *count*, not size). An earlier version of
  this module ran `time.perf_counter` and `tracemalloc` together on the same
  pass, silently reporting the tracemalloc-inflated duration as if it were
  the clean one - caught by comparing this command's own output against the
  plain `credlens synthetic generate` timing for the identical run, which
  disagreed by ~8x. See docs/performance_optimization.md.
"""

from __future__ import annotations

import cProfile
import pstats
import time
import tracemalloc
from dataclasses import dataclass
from io import StringIO

from credlens.generation.orchestrator import generate_scenario


@dataclass(frozen=True)
class ProfileResult:
    scenario: str
    scale: str
    seed: int
    duration_seconds: float
    peak_memory_mb: float
    current_memory_mb: float
    global_content_hash: str
    table_row_counts: dict[str, int]
    top_functions_by_cumulative_time: str

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "scale": self.scale,
            "seed": self.seed,
            "duration_seconds": round(self.duration_seconds, 3),
            "peak_memory_mb": round(self.peak_memory_mb, 3),
            "current_memory_mb": round(self.current_memory_mb, 3),
            "global_content_hash": self.global_content_hash,
            "table_row_counts": self.table_row_counts,
        }


def profile_generation(
    *, scenario: str, scale_name: str, seed: int, top_n: int = 20
) -> ProfileResult:
    # Pass 1: plain timing, no instrumentation of any kind active.
    t0 = time.perf_counter()
    outcome = generate_scenario(scenario=scenario, scale_name=scale_name, seed=seed, force=True)
    duration = time.perf_counter() - t0

    # Pass 2: tracemalloc, for peak memory only - this pass's OWN duration
    # is not reported as "the" duration (see module docstring).
    tracemalloc.start()
    generate_scenario(scenario=scenario, scale_name=scale_name, seed=seed, force=True)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Pass 3: cProfile, for the hotspot breakdown only - same reasoning.
    profiler = cProfile.Profile()
    profiler.enable()
    generate_scenario(scenario=scenario, scale_name=scale_name, seed=seed, force=True)
    profiler.disable()

    buffer = StringIO()
    stats = pstats.Stats(profiler, stream=buffer)
    stats.sort_stats("cumulative")
    stats.print_stats(top_n)

    manifest_tables = outcome.manifest["tables"]
    assert isinstance(manifest_tables, dict)
    table_row_counts = {name: int(t["row_count"]) for name, t in manifest_tables.items()}

    return ProfileResult(
        scenario=scenario,
        scale=scale_name,
        seed=seed,
        duration_seconds=duration,
        peak_memory_mb=peak / 1e6,
        current_memory_mb=current / 1e6,
        global_content_hash=str(outcome.manifest["global_content_hash"]),
        table_row_counts=table_row_counts,
        top_functions_by_cumulative_time=buffer.getvalue(),
    )
