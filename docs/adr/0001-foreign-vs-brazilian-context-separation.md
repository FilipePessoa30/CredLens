# ADR 0001: Separation Between Foreign Public Datasets and Brazilian Market Context

## Status

Accepted (Phase 2, restated and reinforced in Phase 3).

## Context

CredLens uses two individual-level public credit datasets (Taiwan, 2005; Germany, 1970s) as benchmarks, and two Banco Central do Brasil SGS series as market context, for a fictional *Brazilian* digital lender scenario. These sources describe different countries, decades, and populations. Blending them - even implicitly, by presenting a Taiwanese client's record alongside a Brazilian delinquency rate as if they described the same portfolio - would fabricate a relationship that does not exist and would misrepresent both sources.

## Decision

Individual-level sources (`uci_default_credit`, `south_german_credit`) and aggregate market-context sources (`bcb_sgs_20570`, `bcb_sgs_21112`) are kept in strictly separate roles (`primary_benchmark`/`secondary_benchmark` vs. `market_context` - see `data/metadata/dataset_roles.yaml`) and are never joined at the row level. `macro_context_monthly` (Phase 3) re-expresses the BCB series at operational grain specifically so a future join target exists for *synthetic* Brazilian contracts - never for the two foreign individual-level datasets.

## Alternatives considered

- **Treat all four sources as one blended "credit risk" dataset.** Rejected: would imply Taiwanese/German individuals are Brazilian, or that BCB aggregates describe them - a factual misrepresentation.
- **Drop the foreign datasets and use only BCB aggregates.** Rejected: BCB series have no individual-level records at all, so there would be nothing to build individual-level benchmark analysis on (see `docs/dataset_selection.md`).
- **Convert foreign currencies/scales to a "Brazilian-equivalent" figure.** Rejected: would fabricate a conversion basis that doesn't exist and imply false comparability.

## Consequences

- Individual-level benchmark work (Phase 2-onward) never claims Brazilian representativeness.
- The synthetic operational layer (Phase 3+) is the only place individual-level *and* Brazilian-context data can coexist, because it is entirely fictional by construction - no real foreign individual is involved.
- Every document referencing these sources (`docs/data_sources.md`, `docs/assumptions_and_limitations.md`, `docs/sensitive_attributes.md`) repeats this separation rather than assuming a reader remembers it from one place.

## Risks

- A future contributor could accidentally join `uci_default_credit`/`south_german_credit` to `macro_context_monthly` believing it adds useful context. Mitigated by this ADR and repeated warnings in `docs/business_rules.md` and the `macro_context_monthly` contract's own description field.
