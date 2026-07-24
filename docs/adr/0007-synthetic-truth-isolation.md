# ADR 0007: Isolation of the Synthetic-Truth Layer

## Status

Accepted (specified; not implemented - the layer itself is not built in this phase).

## Context

Validating a future synthetic generator (does it actually reproduce the distributions/behaviors it was designed to, is it well-calibrated, does a model trained on its output perform as expected) requires comparing generated *observable* data against the *latent* parameters the generator used to produce it - true segment, true default propensity, the exact random draws made. No real operational system has access to this kind of ground truth about its own customers; it is a property of the simulator, not of a real portfolio.

## Decision

This "synthetic truth" is specified as a conceptually separate layer (`docs/conceptual_data_model.md` section 4.17, `docs/synthetic_generation_spec.md`'s "Known truth") with the following properties, decided now even though the layer is not built until a generator exists:

- Never used as a model feature.
- Never exposed to an operational dashboard or any presentation-layer artifact.
- Git-ignored, exactly like `data/raw/` (see `.gitignore` and `data/README.md`).
- Marked `synthetic_truth_only`, physically separate from every table in `contracts/operational/`.
- Used only for generator validation (distribution recovery, calibration, drift, model-performance benchmarking against known truth, policy-attribution checks).

No contract file exists for it in `contracts/operational/` - creating one now, before the layer itself is designed in detail, would risk exactly the kind of "aparentar implementação" (looking implemented without being implemented) this project's broader rules prohibit.

## Alternatives considered

- **Store latent truth as extra columns on `customers`/`contracts` with a `_truth` suffix.** Rejected during Phase 3 contract design (an earlier draft of `customers.yaml` did exactly this, with a `synthetic_segment` column) - caught in review as contradicting the physical-separation principle this same ADR states, and removed. Kept here as a documented near-miss rather than silently corrected.
- **Don't record latent truth at all; validate the generator only by eyeballing its output.** Rejected: makes generator calibration/regression testing impossible - without recorded truth, there's no way to check "did the generator actually produce what it intended to."

## Consequences

- Whoever builds the generator (Phase 4+) has a stated, agreed boundary for what belongs in this layer before writing any generation code - reducing the risk of truth columns leaking into operational tables the way the near-miss above almost did.
- No code in this repository reads, writes, or references a synthetic-truth table today, because none exists - `docs/synthetic_generation_spec.md` and this ADR are the only artifacts.

## Risks

- Without an implemented contract for this layer yet, there's nothing to mechanically stop a future generator from re-introducing the near-miss (truth columns on operational tables) unless the person implementing it reads this ADR first. Mitigated by cross-referencing this ADR from `docs/conceptual_data_model.md`, `docs/synthetic_generation_spec.md`, and every operational contract's own "deliberately not included" comments (e.g. `contracts/operational/customers.yaml`).
