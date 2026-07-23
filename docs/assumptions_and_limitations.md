# Assumptions and Limitations

This document exists so nobody reading this repository — a recruiter, a hiring manager, a technical reviewer, or a future contributor — mistakes CredLens for a real operational system or a real risk assessment. It is a portfolio project. These constraints apply to every phase of the project, not only the current one.

## Fictional scenario

- The company described in `docs/project_charter.md` and `docs/business_problem.md` is **entirely fictional**. It does not represent any real lender, past employer, or client.
- No real customer exists in this project, at any phase.
- No real personal data, financial account data, or credit bureau data will be used at any phase. Public datasets used in later phases (see `docs/data_strategy.md`) are, by their own publishers' design, anonymized/de-identified research or competition data — not live customer records — and their licenses will be checked before use regardless.

## Not usable for real credit decisions

- Nothing produced by this project — now or in any future phase — may be used to make a real credit decision about a real person or real applicant.
- Any model, score, or simulator this project eventually builds is a **demonstration of method**, not a validated decision system.
- Real-world use of anything resembling this project's outputs would require, at minimum: regulatory review (jurisdiction-specific credit and fair-lending law), legal review, independent statistical validation, bias/fairness testing against protected classes, model governance sign-off, and ongoing operational monitoring — none of which this project performs or claims to perform.

## Bias risk

- Any dataset (public or synthetic) reflects the biases of how it was collected, labeled, or generated. A model trained on it can encode and amplify those biases.
- This project will document known limitations of any dataset it uses (see `docs/data_strategy.md` as it's updated in later phases), but documenting a limitation is not the same as correcting it — a documented-but-uncorrected bias is still a live limitation.
- No fairness certification is claimed or implied by anything in this repository.

## Correlation, prediction, and causality are different things

- A pattern observed in data (e.g., "segment A has higher delinquency than segment B") is, by default, a **correlation** — it does not by itself explain *why*.
- A **prediction** (e.g., a PD model's output) can be useful without being causal — it says "this looks like past cases that defaulted," not "this factor causes default."
- A **causal claim** (e.g., "raising the cutoff by X points would reduce delinquency by Y") requires an explicit causal-inference method (e.g., a designed experiment, a quasi-experimental design, or a stated and defended set of assumptions) — it does not follow automatically from a predictive model or an observed correlation.
- This project commits, throughout `docs/business_problem.md` and in any future analysis, to labeling which of these three a given statement is. A future "policy simulator" phase, in particular, must be explicit that it produces model-based estimates under stated assumptions, not proven causal effects.

## Limitations of synthetic data

- Synthetic data (once generated, in a later phase) is only as realistic as the assumptions coded into its generator.
- It cannot be used as evidence about real-world credit-risk relationships — only as a way to exercise the pipeline, the KPIs, and the code end-to-end when public data alone doesn't provide enough structure (e.g., time-series depth for vintage analysis).
- Synthetic and public data will be kept distinguishable by construction (see `docs/data_strategy.md`) so that no report can accidentally present a synthetic number as an observed one.

## No claim of real financial impact

- This project will not claim a dollar amount saved, a percentage of loss reduced, a return on investment, or any other real financial outcome, because it does not operate against a real business.
- Any example number that appears anywhere in this project's documentation, if truly unavoidable for illustration, must be explicitly and unambiguously labeled as a hypothetical example — never presented as a measured or achieved result. As of this phase, no such example numbers have been used, because it has been possible to avoid them entirely.

## Model risk (future phases)

- Any model built in a later phase will be interpretable-by-design where feasible, precisely so its limitations can be inspected rather than hidden behind a black box.
- Any deployed (in the demo sense) model will need documented monitoring for **data drift** (input distributions changing over time) and **concept drift** (the relationship between inputs and the target changing over time) before its outputs could be trusted to remain valid — this project will document the need for such monitoring even in phases where it doesn't fully implement it, rather than staying silent about the gap.

## Scope limitation of this document

This document will be revisited and extended as each new phase in `docs/roadmap.md` lands — a limitation specific to data acquisition, modeling, or simulation will be added here (or in a phase-specific document it links to) at the point that phase actually introduces the relevant risk, not invented in advance of the work existing.
