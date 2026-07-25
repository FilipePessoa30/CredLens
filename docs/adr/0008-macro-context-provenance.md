# ADR 0008: Row-Level Provenance for Macro/Market Context

## Status

Accepted.

## Context

Phase 3's `macro_context_monthly` contract was classified `synthetic_operational` at the table level, even though every row it actually held (or was ever populated by) was unmodified Banco Central do Brasil SGS data - real, public, individual-level-anonymous market context, not a generated fact about any synthetic customer. A future `macroeconomic_stress` scenario (still `requires_calibration`, not built) would need to inject synthetic macro shocks into a comparable table. Classifying the whole table as one thing or the other is wrong in both directions: calling real BCB data "synthetic" misrepresents its actual provenance; calling the whole table "public" would make a future stress scenario's injected rows silently look like real BCB observations.

## Decision

`macro_context_monthly` keeps a single table (not split into two), but every row now self-declares its own provenance via three columns: `source_type` (`public_bcb_observation` / `synthetic_shock` / `derived_index`), `source_id` (which concrete source produced it), and `is_synthetic` (a redundant, explicit boolean marker, matching the pattern already used on `generation_runs.is_synthetic`). A new business rule, `macro_context_provenance_consistent`, mechanically enforces that these three columns agree with each other - a real BCB row can never be marked synthetic, and a synthetic/derived row can never be marked non-synthetic. Three new `Classification` enum values were added (`public_market_context`, `synthetic_market_context`, `derived_context`); the contract's own top-level classification is `public_market_context` because, in this phase's baseline-only scope, every row it actually produces is real BCB data - the row-level columns exist so a future scenario can add synthetic rows without a breaking schema change or a misleading top-level label.

## Alternatives considered

- **Two separate contracts** (`macro_context_monthly` for real data, `macro_shock_events` for synthetic ones). Rejected for this phase: the generator's temporal-dependence logic needs to join macro context against `account_monthly_snapshots.snapshot_date` uniformly regardless of whether a given month's value is real or (eventually) shock-adjusted; splitting the table would require that join logic to always union two sources instead of reading one. Revisit if the shock model turns out to need materially different columns.
- **A per-column `is_synthetic` flag only, no `source_type`/`source_id`.** Rejected: `is_synthetic` alone tells a consumer *that* a row isn't real, but not *what it is instead* (which shock scenario, which derivation) - `source_type`/`source_id` carry that.

## Consequences

- No downstream query can silently treat a real BCB observation as if it were a generated fact, or vice versa, without an explicit, validated row-level marker to check.
- The `macroeconomic_stress` scenario (still locked) can be implemented later by adding rows with `source_type=synthetic_shock`/`is_synthetic=true` without any schema change - only new data, validated by the same rule.

## Risks

- The mechanical check only verifies internal consistency between `source_type`/`source_id`/`is_synthetic`/`series_code` - it cannot verify that a row's `source_id` genuinely traces back to a real BCB acquisition (that trust boundary is `data/metadata/file_manifest.csv` and `credlens data verify`, upstream of this contract).
