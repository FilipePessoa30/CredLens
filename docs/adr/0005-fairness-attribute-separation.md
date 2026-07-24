# ADR 0005: Physical Separation of Fairness/Evaluation Attributes

## Status

Accepted.

## Context

A future model-fairness audit needs demographic-style attributes (age bracket, region, and similar) to evaluate outcomes across groups. Those same attributes, if available as ordinary model features, could be used (deliberately or accidentally) as direct model inputs - a substantively different and much more sensitive use than retrospective auditing. `docs/sensitive_attributes.md` (Phase 2) already documents this risk for the real acquired datasets, where the attributes are simply columns among many others with no structural protection.

## Decision

For the synthetic operational layer, fairness-relevant attributes live in their own table, `fairness_attributes`, classified `evaluation_only` with every column marked `available_for_modeling: false` - never merged into `application_features` (the table a future model would train on). See `docs/fairness_data_design.md` for the full design rationale.

## Alternatives considered

- **One combined `application_features` table with a `sensitivity` flag per column.** Rejected: a per-column flag is easy to overlook in a future SELECT * or an ad hoc join; a separate table name is a much harder mistake to make by accident, and shows up immediately in a code review or a data-lineage tool.
- **Omit fairness attributes from the schema entirely, add them only when a fairness audit phase actually starts.** Rejected: designing the separation now, while the schema is still being defined, is far cheaper than retrofitting it after `application_features` already has established consumers assuming its current column set is exhaustive.

## Consequences

- Any future fairness audit has a ready-made, clearly-scoped table to join against model outputs.
- Any future modeling code that wants to (incorrectly) use these attributes as features must explicitly join a table named and classified as off-limits - a deliberate, visible act, not an accident.
- This does not, by itself, prevent proxy discrimination through correlated features that do live in `application_features` - `docs/fairness_data_design.md` states this limitation explicitly and repeatedly, because it is the most likely way this protection could be misunderstood as sufficient.

## Risks

- A future contributor could still misuse `fairness_attributes` (e.g. joining it into a training set despite its classification) - the contract's `classification` field and `available_for_modeling: false` markers are documentation and a validation signal, not a runtime access-control mechanism; enforcing that at the code level is a later phase's concern (see `docs/roadmap.md`).
