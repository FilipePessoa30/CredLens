# contracts/

Data contracts: machine-validated declarations of what a table *should* look like, loaded and checked by `src/credlens/contracts/` (`credlens contracts validate`). See `docs/data_contracts.md` for the full narrative and `docs/business_rules.md` for the business rules referenced by `business_rules[].code` below.

## Layout

```text
contracts/
├── raw/            # Contracts for the 4 public sources acquired in Phase 2
└── operational/    # Contracts for the future synthetic operational layer (Phase 3: schema only, no data)
```

## Contract schema (every YAML file here follows this shape)

```yaml
name: <contract name, matches the file name without extension>
version: 1
description: "..."
owner: "<conceptual owner, e.g. 'Risk (conceptual)' - no real org chart implied>"
classification: public_source | synthetic_operational | evaluation_only | synthetic_truth_only | technical_metadata
grain: "<one sentence: what one row represents>"
status: draft | active | deprecated
evolution_policy: "<how this contract is allowed to change over time>"
format: csv | json | asc        # how credlens.contracts reads a file for this contract

primary_key: [<column>, ...]

foreign_keys:
  - {column: <col>, references_contract: <other contract name>, references_column: <col>, severity: error | warning}

columns:
  - {name: <col>, type: string|integer|decimal|boolean|date|timestamp|categorical,
     nullable: true|false, domain: null | {in_set: [...]} | {min: n, max: n} | {regex: "..."},
     unit: <string or null>, temporality: <role or null>,
     sensitivity: public_source|synthetic_operational|evaluation_only|synthetic_truth_only|technical_metadata,
     available_for_modeling: true|false, description: "..."}

uniqueness_rules:
  - {name: <rule name>, columns: [<col>, ...], severity: error | warning}

business_rules:
  - {code: <stable rule code, implemented in src/credlens/contracts/*_rules.py>, description: "...", severity: error | warning}

strict_unexpected_columns: true | false   # if true, an undeclared column is an error in strict mode, not just a warning
```

## Two validation modes (see `src/credlens/contracts/validators.py`)

- **`audit`** — for `raw/` (third-party, already-acquired public data). Never modifies data. A missing required column is always an error; an unexpected column is a warning unless `strict_unexpected_columns: true`. Findings are reported; the command still exits 0 (diagnostic, matching `credlens data audit`'s behavior from Phase 2) unless the file itself can't be read.
- **`strict`** — for `operational/` (the future synthetic layer) and its test fixtures. Any `severity: error` finding fails the run (non-zero exit). Used to gate a synthetic generator's own output once it exists (Phase 4+) — nothing generates data yet in this phase.

## What "no eval" means here

Domain rules (`in_set` / `min` / `max` / `regex`) and business rules (`code`) are **data, not code**. A contract YAML can only select from a small, closed vocabulary that `src/credlens/contracts/domain_rules.py` and the `*_rules.py` modules implement and test — it can never embed an arbitrary Python expression. See `docs/adr/0006-audit-vs-strict-validation.md`.

## Explicitly not here yet

No contract for a "synthetic truth" table exists, because that layer is not built in this phase — see `docs/conceptual_data_model.md` section 4.17 and `docs/roadmap.md`. No contract in `operational/` has ever been validated against real generated data, because none exists yet; they are validated here only against small artificial fixtures (`tests/fixtures/contracts/`).
