# Synthetic Generation Specification

This document specifies the synthetic operational-data generator design across all 6 scenarios. **As of Phase 4A, one of those six - `baseline` - is actually implemented**: `credlens synthetic generate --scenario baseline --scale {smoke,sample,portfolio} --seed N` runs a real, deterministic generator - see `docs/synthetic_generation_implementation.md` for the as-built design, and `docs/adr/0002-synthetic-operational-layer.md`. Every other scenario (`policy_expansion`, `policy_tightening`, `macroeconomic_stress`, `collections_change`, `data_quality_incident`) remains unimplemented - `credlens synthetic generate --scenario <other>` is rejected before any generation runs, exactly as this document originally specified for all six.

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

- **Seed**: `generation_runs.seed`, one explicit integer per run - not a global process-level seed, so multiple runs (e.g. different scenarios) don't interfere with each other's randomness. **Implemented for `baseline`** as of Phase 4A via `credlens.generation.rng.RunRandomStreams` - see `docs/synthetic_generation_implementation.md`.
- **Determinism**: the same `(seed, config_hash)` pair must produce byte-identical output - **implemented and verified for `baseline`** as of Phase 4A, via canonical (order-independent) per-table and global content hashing rather than a literal byte-for-byte Parquet comparison; see `docs/synthetic_generation_implementation.md` "Reproducibility" for why, and `tests/test_generation_orchestrator.py` for the proof (same seed → identical hash, different seed → different hash).
- **Versioning**: `generation_runs.generator_version` and `config_version` record which generator code and which blueprint version produced a run - populated for real by `baseline` runs as of Phase 4A.
- **Config hash**: `generation_runs.config_hash` is a hash of the fully-resolved `GenerationConfig` (`credlens.generation.manifest.canonical_config_hash`) - implemented for `baseline`.
- **Manifest**: implemented for `baseline` - every run writes `manifest.json` (seed, config hash, per-table and global canonical hashes, row counts, timing) into its own run directory; see `docs/synthetic_generation_implementation.md` "Output layout".
- **Post-generation validation**: implemented for `baseline` - every run validates its own output against `credlens.contracts` in strict mode before being promoted from staging to its final location; a failing run is marked `failed` and never presented as valid. See `docs/synthetic_generation_implementation.md` "Validation and atomicity".

## Known truth (synthetic-truth layer)

A generator needs to record, for its own later validation (calibration checking, drift analysis, model-performance benchmarking against ground truth), parameters no real operational system would ever have. **As of Phase 4A, `baseline` records one such parameter for real**: a per-customer/contract latent payment propensity (`credlens.generation.truth`), written only to `data/synthetic_truth/<run_id>/` - see `docs/synthetic_generation_implementation.md` "Synthetic-truth isolation". The fuller set below remains specified but not all implemented:

- The latent segment actually assigned to each customer. *(Baseline implements a single scalar propensity, not a full discrete segment label - a simplification, not the full design.)*
- The true default/payment propensity used to simulate each contract's outcome. **(Implemented for baseline.)**
- The true response-to-collections propensity used to simulate `collection_events` outcomes. *(Not implemented - baseline's collection events are decided from DPD thresholds alone, not from a separate latent responsiveness parameter.)*
- The exact random draws or probabilities used at each simulated decision point. *(Not recorded individually - the run's seed plus its recorded config make the sequence of draws reproducible without needing to store each one.)*

This layer is specified here and in `docs/conceptual_data_model.md` section 4.17. It has no contract file (deliberately - see `docs/adr/0007-synthetic-truth-isolation.md`) and, per its design, is: never used as a model feature (`decisions.compute_decision_score` only ever reads `application_features`), never exposed to an operational dashboard, git-ignored exactly like `data/raw/`, and physically separate from every table in `contracts/operational/`.

## What this specification deliberately leaves open

Every `pending` parameter across the six blueprints is a genuine open design question, not an oversight - `credlens synthetic validate-blueprints` reports the count of `pending` vs. `requires_calibration` vs. `specified` parameters per scenario precisely so this remains visible and trackable rather than getting lost in prose.
