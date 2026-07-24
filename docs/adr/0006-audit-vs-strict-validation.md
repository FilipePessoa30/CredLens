# ADR 0006: Distinct `audit` and `strict` Validation Modes (and the Pydantic/pandas split)

## Status

Accepted.

## Context

This phase validates two very different kinds of table against contracts: already-acquired, immutable third-party public data (`contracts/raw/*`, real files, cannot be "fixed" - see `docs/data_quality_audit.md`), and a not-yet-built synthetic operational layer that, once it exists, should never be allowed to violate its own schema (`contracts/operational/*`). Treating both the same way is wrong in both directions: failing the command on every raw-data quirk would make `credlens contracts validate` useless for its Phase 2 audit role (raw data often *should* show findings without that being a build failure); silently ignoring a violation in the synthetic layer would defeat the entire purpose of having contracts for a system meant to gate a future generator's output.

A second, related design question: how should contract *metadata* (the YAML files) and *table data* (the rows) each be validated? This phase's brief explicitly asked for an evaluation of Pydantic vs. Pandera vs. JSON Schema vs. hand-written validators, and explicitly warned against validating large amounts of row data with a one-object-per-row OO approach.

## Decision

**Two modes, same rule set:** `audit` (raw sources) never fails the command - findings are reported, but a `credlens contracts validate --mode audit` exit code stays 0 unless the file itself can't be read, matching `credlens data audit`'s established Phase 2 behavior. `strict` (operational contracts and their test fixtures) fails (exit 1) if any `error`-severity finding exists. Both modes run identical checks (`domain_rules.check_all` plus every `business_rules[]` entry) - only the CLI's response to the result differs. See `docs/data_contracts.md`.

**Pydantic for metadata, vectorized pandas for data:** contract YAML files (small-N, complex nested structure) are parsed and validated with Pydantic (`src/credlens/contracts/models.py`) - justified because hand-rolling equivalent validation for ~20 contracts' worth of nested column/domain/foreign-key/rule specifications would require substantially more code than the Phase 1/2 dataclass pattern, for no vectorization benefit (there's nothing to vectorize - it's ~20 files, not 30,000 rows). Table data is validated with vectorized pandas operations (`.isin()`, `.duplicated()`, `pd.cut()`, boolean masks over whole columns) - never a Python loop instantiating one Pydantic model per row, which would be both slower at real dataset sizes and structurally unable to express cross-row/cross-table rules (e.g. "at most one final decision per application").

## Alternatives considered

- **Pandera for table-data validation.** Considered; not adopted. Pandera's DataFrame-schema style overlaps significantly with what `domain_rules.py` already does directly in ~250 lines of reviewable pandas, and this phase's cross-table business rules (relational/temporal/financial) don't fit Pandera's single-DataFrame schema model cleanly - they'd need custom checks either way, at which point the added dependency buys less than it costs. `docs/architecture.md` still lists Pandera as a *possible* future addition for enforced (not just diagnostic) data contracts at the warehouse layer - not ruled out permanently, just not adopted here.
- **JSON Schema for contract metadata.** Considered; not adopted. JSON Schema would need a second, separate Python-side model layer anyway to get typed objects out of a validated document, which is exactly what Pydantic already provides in one step with better error messages.
- **One validation mode with a `--strict` flag defaulting to off.** Rejected: naming both `audit` and `strict` as explicit, required choices (`--mode` has no default) forces every invocation to state its intent, avoiding an accidental audit-as-strict or strict-as-audit mix-up.

## Consequences

- `credlens data audit`-style diagnostic behavior (Phase 2) and a genuine CI-gating behavior (needed once a generator exists, Phase 4+) both exist today, using the same rule implementations - no duplicated rule logic between "reporting" and "gating" code paths.
- Adding `pydantic` as a new runtime dependency was a deliberate, documented departure from Phase 1/2's minimal-dependency default - justified in `pyproject.toml`'s own comment and here, not silently introduced.

## Risks

- `strict` mode's exit-code gating is only as good as the rules that exist - a future generator could still produce data that passes every current check while being wrong in a way no rule yet catches (see `docs/business_rules.md`'s "specified only" rows for known gaps).
