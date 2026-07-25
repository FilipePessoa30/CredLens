# Performance optimization (Phase 4B)

## Why this work happened

Phase 4A's own report measured the `sample` scale (5,000 customers, 12 months,
~101k rows) at roughly 57.3 seconds. Phase 4B was about to multiply that cost by
five more scenarios plus a `portfolio` scale, so profiling and optimizing the
generator's core came first, before any new scenario was built - exactly as this
phase's own prompt required ("não multiplique esse custo por seis cenários sem
antes perfilar e otimizar").

## Re-measuring the baseline

Before touching any code, `sample` was re-run on this machine, this session, with
the unmodified Phase 4A code (verified via `git stash`): **8.484 seconds**, not
57.3s. The original 57.3s figure was measured under different (noisier) machine
conditions and is not a valid comparison point - see
`reports/synthetic_validation/performance_baseline.json`. All performance claims
in this document compare against the 8.484s figure, measured on this same
machine, with this same code, moments before optimization began.

## Profiling method

Two separate passes were used, deliberately not one:

1. **cProfile** (`cProfile.Profile()` + `pstats.Stats`) on the `sample` scale, to
   find which *functions* were expensive.
2. **Coarse `time.perf_counter()` checkpoints** around each major generation
   phase (population → applications → decisions → booking → schedules → truth →
   ledger simulation → macro → contract loading → validation → hashing →
   writing), run *without* cProfile.

Both were needed: cProfile's own instrumentation overhead turned out to be
severe for this workload (many small Python-level calls inside the ledger
simulation) - the profiled run measured **33.9 seconds**, about 4x the clean
8.484s run for the *identical* call. Trusting cProfile's wall-clock number alone
would have overstated the real cost of everything it touches. cProfile was still
useful for *relative* ranking of functions, and the coarse pass gave real,
undistorted absolute numbers.

Coarse breakdown of the pre-optimization 5.46s-scale reference run (a slightly
different measurement path than the full CLI, see the profiling script in
git history for the exact call sequence):

| phase | seconds | % of total |
| --- | ---: | ---: |
| ledger_simulation (payments.py) | 1.824 | 33.4% |
| schedules (installment generation) | 1.285 | 23.5% |
| strict_validation | 0.934 | 17.1% |
| canonical_hashing | 0.600 | 11.0% |
| parquet_write | 0.183 | 3.4% |
| applications | 0.284 | 5.2% |
| load_contracts_yaml | 0.143 | 2.6% |
| customers / decisions / booking / truth / macro | 0.207 | 3.8% |

## Optimizations applied

All four were verified to leave the canonical content hash **exactly**
unchanged (same seed → same `global_content_hash`, both at `smoke` and `sample`
scale) before being kept - see "Verification" below.

1. **Bulk states construction** (`payments.py`) - `installments.groupby(
   "contract_id")` followed by one `group.to_dict("records")` call *per
   contract* was replaced with a single `installments.to_dict("records")` pass
   plus a plain-Python grouping loop. Profiled at ~9.2s of the 33.9s cProfile
   run - the single largest hotspot found. `installments` is already contiguous
   per `contract_id` in `installment_number` order by construction (see
   `schedules.generate_installments`), so the plain pass preserves the exact
   same per-contract ordering `groupby` would have.

2. **Vectorized canonical table hashing** (`manifest.py`) -
   `DataFrame.apply(lambda row: ..., axis=1)` (builds one pandas `Series` per
   row) was replaced with a single whole-array `.astype(str)` plus a plain
   Python list comprehension over `.to_numpy().tolist()`. Profiled at ~6.7s of
   the 33.9s run - the second-largest hotspot. **A real bug was found and fixed
   while doing this**: the original per-row `.to_numpy(dtype=str)` cast has a
   side effect - numpy's fixed-width unicode cast silently strips a trailing NUL
   byte from the null sentinel (`"\x00NULL\x00"` → `"\x00NULL"`). The naive
   rewrite dropped this cast entirely and produced a *different* hash for every
   table containing a null value. Caught immediately by re-running `smoke` and
   diffing manifests - not by reasoning about the code. Fixed by reproducing the
   exact same cast as a single whole-array operation instead of doing it once
   per row.

3. **Manual month arithmetic in installment scheduling** (`schedules.py`) -
   `first_due + pd.DateOffset(months=k)` constructs a `dateutil.relativedelta`
   object per installment (dateutil's own `__init__`/`__add__`/`__mul__` showed
   up as real cost in the profile). Replaced with a manual year/month/day-clamp
   calculation, verified byte-for-byte equivalent to `pd.DateOffset(months=k)`
   across 200,000 randomized `(date, months)` pairs (covering every day-of-month
   and leap-year edge case) before being adopted.

4. **Head-index installment pruning** (`payments.py`) - each contract's
   `open_installments` list is already sorted by due date at construction, and
   installments are provably exhausted in strict due-date order (payment
   allocation always fills the oldest open installment before touching a newer
   one). A `head_index` pointer, advanced once an installment is permanently
   exhausted, lets every per-month scan (payable amount, DPD, snapshot sums,
   collections eligibility) work over only the genuinely-still-open suffix
   instead of the contract's entire original schedule. **A second real bug was
   found and fixed here**: `account_monthly_snapshots.next_due_date`'s
   computation in `snapshots.derive_snapshot_row` uses an *inclusive* `>=`
   comparison against `month_end` and does *not* filter by remaining balance -
   a pre-existing (if subtle) quirk where an installment due exactly on the
   snapshot date that gets paid off that same month is still briefly counted as
   "next due". Passing the head-index-pruned list into that one specific
   computation would have silently changed this pre-existing behavior for
   same-day payoffs. Found by diffing every cell of `account_monthly_snapshots`
   between the pre- and post-optimization `sample` runs, not by code review -
   the two runs were byte-identical everywhere else. Fixed by keeping that one
   call site on the full (unpruned) list, which is safe because every other
   field this function computes is unaffected either way (exhausted
   installments contribute exactly zero to every other sum).

Deliberately **not** optimized: strict contract validation (a hard,
non-negotiable gate - see docs/adr/0006), Parquet writing (already small), and
one-time YAML contract loading (a fixed cost unrelated to the O(months ×
contracts) loop this phase targeted).

## Verification

Every optimization was checked, in order, before being kept:

1. Regenerate `baseline` @ `smoke`, seed 2026 - compare `global_content_hash`
   against the pre-optimization value.
2. Regenerate `baseline` @ `sample`, seed 2026 - same check.
3. `uv run pytest` - full suite, no regressions.
4. `uv run mypy src tests` / `uv run ruff check .` - clean.

Two optimizations (steps 2 and 4 above) initially broke the hash and were
debugged and fixed before being kept - see the numbered bug descriptions above.
A third, unrelated bug was found and fixed while building `credlens synthetic
profile` itself (not one of the four optimizations, but part of this phase's
tooling): its first version measured `time.perf_counter` and `tracemalloc`
together on the same pass, and `tracemalloc`'s own instrumentation turned out
to inflate wall time by roughly **8x** on this workload (millions of small
allocations - tracemalloc's overhead scales with allocation count, not size).
The command silently reported this inflated duration as "the" duration - caught
by comparing its output against the plain `credlens synthetic generate` timing
for the identical run (3.9s vs. the profile command's 31-44s). Fixed by
splitting into three separate passes (plain timing / tracemalloc / cProfile),
none of which measures another's overhead - see
`credlens.generation.profiling`.
A significant methodology lesson from this process: the very first "fix
verified" claim for the `macro_shock` config-schema addition (a *different*,
non-performance change made later in this phase) was a **false positive** -
the check was reading a stale, previously-generated manifest file at a
hardcoded path, because the newly-computed `generation_run_id` had silently
changed (a new optional config field changes `config_hash` even when unset,
which changes the id prefix, which changes the run's directory) and the
`--force` flag therefore wrote to a *different* directory than the one being
checked. Fixed by (a) making `canonical_config_hash` exclude unset optional
fields (`model_dump(mode="json", exclude_none=True)`), so adding a new,
scenario-specific config section doesn't churn every other scenario's hash, and
(b) always reading the actually-reported `generation_run_id` from command
output afterward, never a remembered path.

## Result

| | Before | After |
| --- | ---: | ---: |
| `sample` duration (seed 2026, clean run) | 8.484s | 3.734s (range observed: 3.73-3.98s) |
| `global_content_hash` | `ac0a7282...` | `ac0a7282...` (identical) |
| Speedup | - | **~2.27x** |

Meets this phase's "at least 2x" target (section 2.4) with the canonical content
hash preserved exactly - no version bump of the DGP was needed for the
performance work itself. See `reports/synthetic_validation/performance_baseline.json`
and `performance_optimized.json` for the raw numbers.
