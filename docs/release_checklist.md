# Release Checklist — CredLens 1.0 Release Candidate (Phase 10)

Run `credlens release validate`, `credlens release manifest`, and the full test suite before tagging a release. This checklist mirrors the blocking gates `credlens.release.manifest.decide_readiness` evaluates programmatically - it is a human-readable companion to that decision, not a separate source of truth.

## Blocking gates (any failure → `release_candidate_not_ready`)

- [ ] `uv run ruff check .` - no lint errors.
- [ ] `uv run ruff format --check .` - no formatting drift.
- [ ] `uv run mypy src tests dashboard` - no type errors (strict mode).
- [ ] `uv run pytest` (full suite, all markers) - 100% pass, no skipped-without-reason.
- [ ] `uv run pytest --cov=credlens --cov-report=term-missing` - coverage recorded, no module artificially excluded.
- [ ] `uv run credlens warehouse build && uv run credlens warehouse test` - dbt build/test green.
- [ ] `uv run credlens warehouse reconcile` - independent Python reconciliation matches SQL within tolerance.
- [ ] `uv run credlens model validate-independent --model-id MODEL_behavioral_default_v1` - `validation_passed` or `validation_passed_with_limitations`, never `validation_failed`.
- [ ] `uv run credlens monitor evaluate-false-alerts --reference-id REF_MODEL_behavioral_default_v1` - family-wise corrected rate near the demonstrative target (~5% review / ~1% material).
- [ ] `uv run credlens dashboard validate --demo` - demo package structurally valid.
- [ ] `uv run credlens release validate` - every integrity check passes (version, lockfile, license, no secrets, no oversized tracked files, bilingual reports present, official model artifacts present, CI workflow has no tolerance-masking pattern).
- [ ] Documentation present and bilingual: README, model card, technical report, validation report, monitoring report, remediation report, PORTFOLIO, recruiter brief, interview guide.
- [ ] No secret committed (`credlens release validate`'s local-only regex scan; never an external scanner).
- [ ] CI workflow has no `|| true`/`continue-on-error: true` on a critical step (`tests/test_ci_workflow_integrity.py`).

## Classified separately (absence must be visible, but is not on its own a blocker)

- [ ] **Visual QA**: verified with a real browser (headless Selenium/Playwright) locally, or explicitly marked `not_verified` if no browser tool was available in the environment that produced the release.
- [ ] **Docker**: `Dockerfile.dashboard` builds and its container passes an HTTP smoke test, or explicitly marked `not_executed` if the local Docker daemon was unavailable.

## Versioning

- Project version follows `credlens release manifest`'s `readiness_decision`:
  - `release_candidate_ready` (all blocking gates pass AND visual QA verified AND Docker built) → may use a stable version.
  - `release_candidate_ready_with_limitations` (all blocking gates pass, but visual QA and/or Docker were not executed/verified in this environment) → use an `rcN` suffix (e.g. `1.0.0rc1`), never a stable release version.
  - `release_candidate_not_ready` (any blocking gate failed) → do not tag a release.
- Never bump the stable `1.0.0` version while remote CI has not run on the exact commit being released, visual QA remains unverified, or Docker remains untested if Docker is announced as an official execution path.

## Preserved across this phase (never overwritten)

- `DGP 0.6.0` synthetic generation logic and its own version marker.
- `MODEL_behavioral_default_v1` (the original candidate) and all of its artifacts, reports, and lifecycle history.
- `EXP_behavioral_default_v1`'s frozen evidence/predictions.
- Every prior phase's experiment/model/manifest under `reports/modeling/experiments/`, `reports/modeling/models/`.

## Final steps before declaring a readiness decision

1. Run `credlens release manifest --visual-qa-status <status> --docker-status <status> --ci-status <status>` with the REAL, just-observed status of this environment - never a guessed or aspirational value.
2. Read `reports/release/release_manifest.json`'s `readiness_decision` and `release_blockers` - if `release_blockers` is non-empty, the decision MUST be `release_candidate_not_ready`, regardless of how much other work is complete.
3. Record the decision, the blocking-gate results, and every known limitation in the final phase report - never omit a failing gate to make the release look more complete than it is.
