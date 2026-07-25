# Data quality incidents and quarantine (Phase 4B)

## Why this isn't a scenario config

Every other Phase 4B scenario is a different, internally-consistent DGP
(different config, same generator code, always contract-valid). A data quality
incident is the opposite: a deliberately **invalid** table set, produced by
taking an already-valid run and corrupting it. Mixing that into the scenario
config system (`config/synthetic/*.generation.yaml`) would blur "a different
plausible world" with "a world that's broken on purpose" - so
`credlens.generation.quarantine` is a separate module, and `data_quality_incident`
has no `generation.yaml` and stays `requires_calibration` as a scenario
blueprint.

## The flow

1. Generate (or reuse) an already-valid run - `contract_coverage` is used by
   this project's own tests because it's guaranteed to have at least one
   terminal-status contract, which the `incoherent_snapshot` incident needs.
2. Load that run's operational tables into memory (never touching the files on
   disk).
3. Apply **exactly one** controlled defect (`credlens.generation.quarantine.
   INCIDENTS`).
4. Run strict contract validation (`credlens.generation.validation.
   validate_contracts_strict`) against the corrupted tables and confirm the
   *expected* error code appears. If it doesn't, `run_incident` raises
   `IncidentError` - an incident that fails to produce its own claimed failure
   is itself treated as an error, not silently accepted.
5. Only then: write the corrupted tables under
   `data/quarantine/QUARANTINE_<incident_id>_<source_run_id>/`, with
   `generation_runs.status` forced to `quarantined_expected_failure`, plus a
   `quarantine_manifest.json` recording the incident id, expected/found error
   codes, and description.

A quarantined run is **never** written under `data/synthetic/`, **never**
marked `completed`, and is invisible to `credlens synthetic validate/inspect/
manifest` (those commands only resolve run ids under
`config.output.operational_dir`, which is a different directory).

## The five incidents

| `incident_id` | What it injects | Expected error code | Contract |
| --- | --- | --- | --- |
| `duplicate_primary_key` | Duplicates a `customers` row's `customer_id` onto a second row | `PK_DUPLICATE` | `customers` |
| `orphan_foreign_key` | Points an `applications` row's `customer_id` at a customer that doesn't exist | `FK_ORPHAN` | `applications` |
| `invalid_domain` | Sets a `credit_decisions.outcome` to a value outside its declared domain | `DOMAIN_VIOLATION` | `credit_decisions` |
| `incoherent_snapshot` | Duplicates a terminal-status contract's last snapshot one month later | `SNAPSHOT_AFTER_TERMINAL_STATUS` | `account_monthly_snapshots` |
| `impossible_date` | Sets a `credit_decisions.decision_timestamp` before its own application's `submitted_at` | `DECISION_BEFORE_SUBMISSION` | `credit_decisions` |

Each of the five reuses an **existing** contract rule from Phase 3/4A
(`credlens.contracts.domain_rules` and `.temporal_rules`) - no new validation
logic was written for this phase; the incidents exist to prove the existing
rules actually catch these defects when they occur in generator-shaped data,
not hand-authored fixtures.

## Running an incident

```python
from pathlib import Path
from credlens.generation.quarantine import run_incident

outcome = run_incident(
    source_operational_dir=Path("data/synthetic/RUN_.../operational"),
    incident_id="orphan_foreign_key",
    quarantine_base_dir=Path("data/quarantine"),
    source_run_id="RUN_...",
)
print(outcome.found_expected_error, outcome.quarantine_dir)
```

There is no dedicated CLI subcommand for this in Phase 4B (out of scope for
this pass) - `tests/test_generation_quarantine.py` exercises all five incidents
end-to-end and is the reference for how to call this module.

## Never included in the warehouse

Quarantined runs are physically outside `data/synthetic/` specifically so that
no future warehouse-loading step (Phase 5+) could accidentally pick one up by
scanning that directory - this is a structural guarantee, not a naming
convention.
