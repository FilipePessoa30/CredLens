# Interview Guide — CredLens

*Traceable answers to the questions this project is most likely to draw in an interview. Portuguese version: [interview_guide.pt-BR.md](interview_guide.pt-BR.md). Never invents professional banking experience — every answer below is scoped to what this project itself demonstrates.*

## "Why synthetic data for the portfolio layers?"

Because there is no public, realistically-shaped, event-level credit-portfolio dataset (originations, billing cycles, delinquency, collections, cures) that is both free to redistribute and rich enough to build a funnel/vintage/collections analysis on. A documented, seeded, reproducible data-generating process (`credlens.generation`, see `docs/synthetic_generation_spec.md`) makes the analytics layers demonstrable without a real institution's data - at the cost of never being able to claim the numbers reflect real-world behavior. That trade-off is stated explicitly everywhere the synthetic portfolio's numbers appear ("Synthetic data - illustrative portfolio").

## "Why the UCI benchmark for the model, instead of the synthetic portfolio?"

Because a synthetic default label would be circular: the generator would have to encode *some* default rule, and a model trained to predict that rule would only prove it can recover a rule its own creator wrote in. The UCI "Default of Credit Card Clients" dataset (Taiwan, 2005) is real, historical, and has a real default outcome nobody manufactured - so a model trained on it is at least evaluated against genuine behavior, even though that behavior is from a different country, era, and population than any hypothetical Brazilian lender. See `docs/dataset_selection.md` and `docs/target_and_leakage_audit.md`.

## "Why logistic regression as the primary model, not HistGradientBoosting?"

Because the primary deliverable is an *interpretable* behavioral early-warning model with executive-facing reason codes, and a linear model's coefficients decompose additively and exactly into a per-feature contribution - no approximation needed. HistGradientBoosting is deliberately kept as a **challenger**, never promoted: Pareto-compared against the logistic candidate on discrimination, calibration, stability, robustness, size, and latency (`credlens model compare-candidates`), consistently showing higher raw discrimination (ROC-AUC 0.780 vs 0.745) at the cost of interpretability. Both facts are reported side by side - the project never hides that the linear model is not the best-discriminating option, only that it was the right one for the stated interpretability requirement.

## "How was leakage avoided?"

A static feature-registry allowlist (`config/modeling/feature_registry.yml`) is the *only* path a column can take into training - nothing reaches the estimator that isn't on it, and demographic columns (SEX/EDUCATION/MARRIAGE/AGE) are never on it (post-hoc audit only). Five functional negative controls run every time a model is trained: a shuffled-target control, a near-perfect-discrimination detector, an ID-only-features control, and direct rejection of the target column or an exact copy of it as a feature. See `docs/target_and_leakage_audit.md` and `credlens.modeling.leakage`.

## "How were the KPIs defined?"

Every KPI has an explicit formula, grain, and owner in `docs/kpi_dictionary.md`/`config/kpi_catalog.yml` *before* any SQL was written against it - the dbt marts implement the catalog, not the other way around. Each KPI computed in SQL is independently re-derived in Python and reconciled within a documented tolerance (`credlens warehouse reconcile`), so "the dashboard number" and "the SQL number" are never two unverified guesses.

## "How was the model validated?"

Twice, by two different packages. `credlens.modeling` computes the original discrimination/calibration/subgroup/robustness suite at training time. `credlens.model_validation` - a *separate* package - re-derives every one of those numbers from FROZEN evidence, never copying the original report, and additionally runs two independent permutation-based negative controls: a classical label-permutation test on frozen predictions (999 resamples) and a full-pipeline retrain test with a shuffled training target (100 resamples), both at α=0.01. The 14-gate decision is `validation_passed_with_limitations` - see `reports/model_validation/validation_report.md`.

## "Why did monitoring produce false alerts, and how was it recalibrated?"

The original per-feature drift threshold was calibrated correctly for a SINGLE feature in isolation (a 95th-percentile cutoff), but was then applied to 18 features independently every batch - a textbook multiple-comparisons problem. An empirical audit this release measured the real consequence: ~60% of genuinely normal batches (no injected drift at all) tripped at least one alert. The fix was a second, family-wise-calibrated threshold (calibrated on the *maximum* PSI across all 18 features per resample, not one feature's own marginal null), which brought the same measurement down to ~4%/1% (review/material) - documented in `config/monitoring/thresholds.yml` and `credlens.monitoring.calibration_study`.

## "What would change with real institutional data?"

The target would need a real, legally-defined default outcome (not a benchmark's own label); the feature set would need underwriting/behavioral variables validated against actual charge-off experience; subgroup fairness analysis would need to be a compliance review, not a diagnostic; the monitoring reference would need a real production scoring stream instead of a partitioned historical test set; and every "not suitable for real lending decisions" disclaimer in this project would need to be replaced by an actual model-risk-governance sign-off process - which is exactly the kind of process this project's structure (independent validation, documented gates, monitoring, versioned decisions) is modeled on, without claiming to BE one.

## "Which part demonstrates SQL?"

`warehouse/` - 64 dbt models (raw → staging → intermediate → dimensions → facts → marts) over DuckDB, 135+ generic/singular tests, window functions for vintage/cohort analysis, and the independent Python reconciliation that proves the SQL is right rather than merely asserting it. See `docs/warehouse_architecture.md`.

## "Which part demonstrates software engineering, not just analysis?"

The CLI (`credlens ...`, dozens of subcommands, each independently testable), the layered package structure (`generation` → `warehouse` → `analysis` → `dashboard` and, separately, `modeling` → `model_validation` → `monitoring`, each depending only downward, never sideways or up), strict `mypy`, `ruff` lint+format, 1,599 tests at 94% coverage, and a CI workflow split into 8 parallel jobs with no masked failures (`tests/test_ci_workflow_integrity.py` fails the build if a `|| true`-style pattern ever reappears).

## "Which part demonstrates executive communication?"

The bilingual (English/Portuguese) model cards, technical reports, and validation/monitoring reports - each written for a specific reader (an executive summary states the decision and the limitation in the first paragraph, never buries it), and the dashboard's "Illustrative review-capacity scenario" framing on every operating-point simulation, which states plainly that no threshold shown is profit-optimized or a recommended policy.

## "What decisions can this project NOT make for a real business?"

Whether to approve a specific applicant (no origination score exists here); where to set a profit-optimal cutoff (thresholds are illustrative capacity scenarios only); whether the model is fair under a specific jurisdiction's legal standard (subgroup diagnostics are not a fairness certification); how the portfolio would actually perform under a real macro shock (the synthetic scenarios are counterfactual, not forecasts). Every one of these boundaries is stated in the model card and the dashboard's own provenance labels, not left implicit.
