"""Independent model validation (Phase 9).

This package is deliberately SEPARATE from `credlens.modeling` (the
training-time package it audits): it reads frozen artifacts (predictions,
experiment records, registered model manifests) and either recomputes
evidence with its own implementation or explicitly re-derives it from raw
counts, rather than calling the exact function that produced the
original number. See `reports/model_validation/validation_report.md` for
the full methodology and `docs/model_validation_scope.md`... (this
package does not read or write anything under `credlens.modeling`'s own
report directory except as read-only input).

Never implements: an API, a deploy path, automatic retraining, automatic
promotion to production, or a credit decision. See
`credlens.model_validation.decision` for the only three allowed outcomes:
`validation_passed`, `validation_passed_with_limitations`,
`validation_failed`.
"""

from __future__ import annotations
