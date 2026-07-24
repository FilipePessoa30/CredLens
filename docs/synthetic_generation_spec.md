# Synthetic Generation Specification

This document specifies the future synthetic operational-data generator. **No generation code exists in this phase** - `credlens synthetic generate` returns `Not implemented: scheduled for the synthetic generation phase.` and exits non-zero, on purpose (see `docs/roadmap.md` phase 4). What exists today: the target schema (`contracts/operational/*.yaml`), this specification, and six structurally-validated-but-uncalibrated scenario blueprints (`config/synthetic/scenarios/*.blueprint.yaml`).

## Population

- **Customer creation**: synthetic `customers` rows are created over the simulated period (`generation_runs.period_start` to `period_end`), not all at once - the exact arrival pattern (constant rate, growth curve, etc.) is `requires_calibration` in every blueprint.
- **Applications per customer**: a customer may submit more than one `applications` row over time (e.g. a rejected application followed later by a successful one, or a repeat customer) - the distribution governing this is `requires_calibration`.
- **Temporal distribution**: application arrival within the period is not assumed uniform - whether/how it varies (see "Temporal dependence" below) is a separate, explicitly named parameter.
- **Latent segments**: the generator would assign each customer to a latent segment (see "Known truth" below) that influences - but is never directly stored as - its origination and performance outcomes. This is distinct from `fairness_attributes` (see `docs/fairness_data_design.md`) - segments are a generator mechanism, not a demographic label.

## Origination (Concessão)

- **Policy application**: every `credit_decisions` row references exactly one `policy_versions` row, valid at `decision_timestamp` (enforced today by `approval_requires_valid_policy` against whatever data exists - see `docs/business_rules.md`).
- **Approve/reject**: driven by the customer's latent segment plus `application_features` in a way the generator controls (not necessarily a simple threshold) - the exact function is undesigned (`requires_calibration`).
- **Amount and term**: approved amount/term may differ from requested amount/term (a partial approval) - the generator must be able to produce both matches and reductions, not always approve exactly what was requested.
- **Approval without contracting**: the generator must produce some applications that reach `credit_decisions(outcome=approved, is_final=true)` with **no corresponding `contracts` row** - this is a required scenario (`docs/business_rules.md`'s "approval does not imply a contract"), not an edge case to avoid.
- **Policy changes**: `policy_expansion` and `policy_tightening` blueprints specify exactly one policy-change event mid-period; `baseline` and the others specify zero.

## Performance (Desempenho)

- **On-time payment**: the common case - `payments`/`payment_allocations` rows that fully cover each `installments` row by its `due_date`.
- **Prepayment**: payment before `due_date`.
- **Delinquency**: payment after `due_date`, or not at all, producing DPD > 0 per `docs/metric_semantics.md`'s convention.
- **Partial payment**: a `payments` row whose allocated amount doesn't fully cover an installment's `scheduled_total`.
- **Cure**: a contract returning from `delinquent` to `active` (see `docs/state_machines.md`).
- **Reincidence**: a cured contract becoming delinquent again later - the generator must not treat cure as a one-way, permanent state.
- **Write-off**: per a to-be-defined policy threshold (see `docs/metric_semantics.md`'s open "Default" definition - the write-off policy and the default-label definition are related but not required to be identical, and the generator must be explicit about which one drives which behavior).
- **Recovery**: post-write-off, per `write_off_events` -> `recovery_events`, ordered per `recovery_after_write_off`.

None of these behaviors has a calibrated rate in this phase - every blueprint marks `performance.*` as `requires_calibration` or `pending`.

## Temporal dependence

- **Seasonality**: whether/how origination volume or performance varies by calendar month - `pending` in every blueprint (not yet designed, not merely uncalibrated).
- **Mix shift**: whether the population's segment mix drifts over the simulated period, independent of any policy change - `requires_calibration`, not addressed by any blueprint's `population.segment_mix` beyond naming it.
- **Policy-change events**: exactly the mechanism `policy_expansion`/`policy_tightening` specify.
- **Population drift / behavior drift**: general concepts named here; no blueprint parameter currently isolates them from segment mix shift - a design gap for whoever builds the generator, not something quietly assumed solved.
- **Stress scenario**: `macroeconomic_stress`'s single stress window, during which performance parameters worsen, independent of policy.

## Scenarios

| Scenario | Isolates | Blueprint |
|---|---|---|
| `baseline` | Nothing changes - the reference case every other scenario is defined relative to. | `config/synthetic/scenarios/baseline.blueprint.yaml` |
| `policy_expansion` | One policy-loosening event, nothing else. | `policy_expansion.blueprint.yaml` |
| `policy_tightening` | One policy-tightening event, nothing else. | `policy_tightening.blueprint.yaml` |
| `macroeconomic_stress` | One macro stress window, no policy change. | `macroeconomic_stress.blueprint.yaml` |
| `collections_change` | One collections-strategy switch, no policy/macro change. | `collections_change.blueprint.yaml` |
| `data_quality_incident` | One injected data defect, testing `credlens contracts audit` itself rather than portfolio behavior. | `data_quality_incident.blueprint.yaml` |

**No probability is assigned to any scenario** - they are alternative "what if" runs for testing analysis/audit code against different dynamics, not a probabilistic ensemble. Every blueprint's top-level `status` is `requires_calibration` or `draft`, never anything implying readiness to run - see `config/synthetic/README.md`.

## Reproducibility

- **Seed**: `generation_runs.seed`, one explicit integer per run - not a global process-level seed, so multiple runs (e.g. different scenarios) don't interfere with each other's randomness.
- **Determinism**: the same `(seed, config_hash)` pair must produce byte-identical output - not yet implementable (no generator exists) but stated as a hard requirement for whichever phase builds one.
- **Versioning**: `generation_runs.generator_version` and `config_version` record which generator code and which blueprint version produced a run - both required fields already, in the contract, before any generator exists.
- **Config hash**: `generation_runs.config_hash` should be a hash of the fully-resolved blueprint (after any defaults are applied), so two runs claiming the same `config_version` can still be verified to have used identical resolved parameters.
- **Manifest**: a future generator run should produce a manifest analogous to `data/metadata/file_manifest.csv` (Phase 2) for its own output files, with the same checksum/size/row-count discipline - not built in this phase, but the precedent exists and should be reused rather than reinvented.
- **Post-generation validation**: every table a generator produces must pass `credlens contracts validate --mode strict` before being considered a valid run - this phase's contracts and rules are exactly the gate a future generator would need to pass, which is why they were built now rather than alongside the generator itself.

## Known truth (synthetic-truth layer)

A future generator would need to record, for its own later validation (calibration checking, drift analysis, model-performance benchmarking against ground truth), parameters no real operational system would ever have:

- The latent segment actually assigned to each customer.
- The true default/payment propensity used to simulate each contract's outcome.
- The true response-to-collections propensity used to simulate `collection_events` outcomes.
- The exact random draws or probabilities used at each simulated decision point.

This layer is specified here and in `docs/conceptual_data_model.md` section 4.17 - **it is not built in this phase**, has no contract file, and per its design must be: never used as a model feature, never exposed to an operational dashboard, git-ignored exactly like `data/raw/`, and physically separate from every table in `contracts/operational/`. See `docs/adr/0007-synthetic-truth-isolation.md`.

## What this specification deliberately leaves open

Every `pending` parameter across the six blueprints is a genuine open design question, not an oversight - `credlens synthetic validate-blueprints` reports the count of `pending` vs. `requires_calibration` vs. `specified` parameters per scenario precisely so this remains visible and trackable rather than getting lost in prose.
