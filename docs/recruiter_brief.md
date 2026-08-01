# Recruiter Brief — CredLens

*One page. Portuguese version: [recruiter_brief.pt-BR.md](recruiter_brief.pt-BR.md). Full detail: [../README.md](../README.md), [../PORTFOLIO.md](../PORTFOLIO.md).*

## The challenge

Build a credit-portfolio analytics + risk-modeling project that behaves like a real, production-shaped codebase — not a single notebook — while being fully reproducible on a laptop with no external data dependency, and honest about what a historical benchmark and a synthetic portfolio can and cannot prove.

## What was actually done

- Designed and documented a synthetic-portfolio data-generating process (seeded, reproducible, with an explicit truth/observed separation) plus 64 dbt models over DuckDB (staging → marts), each independently reconciled against a Python re-implementation of the same KPI logic.
- Built a portfolio analysis layer (funnel, delinquency, vintages, cure/collections, counterfactual scenarios) and a 10-page Streamlit dashboard, each page covered by automated `AppTest` execution and, this release, a real headless-browser pass.
- Trained an 18-feature interpretable logistic regression (behavioral early-warning default model) on the UCI "Default of Credit Card Clients" benchmark, with full leakage controls, calibration, subgroup diagnostics, and 9 robustness perturbations, plus a HistGradientBoosting challenger.
- Built a *second, independent* validation package that never trusts the model's own reported numbers - it recomputes every metric from frozen predictions and runs two separate permutation-based negative controls (a classical label-permutation test and a full-pipeline retrain test).
- Built a monitoring simulation (drift/performance thresholds calibrated from the model's own reference distribution, a signal → alert → incident escalation hierarchy, a detection-evaluation matrix across 12 documented perturbation scenarios).
- This release cycle re-audited the whole stack for remaining methodological gaps, found and fixed two real, measured problems (a ~60% false-alert rate from an uncorrected multiple-comparisons issue; a ~0.012 ROC-AUC optimism bias in the monitoring performance reference), and built a remediated model variant registered separately from - never replacing - the original.

## Stack

Python (pandas, scikit-learn, DuckDB, dbt-core), Streamlit + Plotly, pytest + mypy (strict) + ruff, GitHub Actions CI (8 parallel jobs), uv for dependency management, Selenium for real-browser dashboard verification.

## Decisions demonstrated

- Choosing a historical public benchmark for modeling (auditability, no fabricated ground truth) over fabricating "real" default labels for the synthetic portfolio.
- Choosing logistic regression as the primary interpretable candidate, with a non-linear challenger for comparison, not the reverse.
- Choosing to disclose a repeatedly-observed holdout rather than call it "untouched" once it no longer was.
- Choosing a family-wise statistical calibration over a fixed, market-generic drift threshold once the fixed threshold was shown to produce excessive false alerts.

## Demonstrated impact (this is a portfolio project — see limitations)

Not a claim of real financial impact. What is demonstrated: a full, auditable analytics-to-monitoring pipeline; a real methodological error found and fixed through independent re-validation, not assumed away; a project that can be reproduced end to end by a stranger from a clean checkout.

## Limitations

Historical, non-Brazilian benchmark; synthetic portfolio; no fairness certification; no legal-compliance claim; not suitable for real lending decisions. See [../docs/assumptions_and_limitations.md](assumptions_and_limitations.md).

## Where to look next

[../PORTFOLIO.md](../PORTFOLIO.md) (2-minute summary) → [../README.md](../README.md) (full technical reference) → [interview_guide.md](interview_guide.md) (specific Q&A).
