# Business Problem

> This document describes a **fictional** company and scenario, used to give this project's analytics work a coherent business narrative. No real company, customer, or financial figure is represented. See `docs/assumptions_and_limitations.md`.

## Fictional business situation

The company at the center of this project — referred to here simply as "the company" — is a digital lender that originates unsecured consumer installment loans through an app and a website. It has been operating for several years, has scaled its loan origination volume over that time, and holds the loans it originates on its own balance sheet (it is not purely a marketplace lender). Like any lender at this stage, its leadership needs to answer one recurring question with evidence rather than intuition:

## The central executive question

> **How do we grow or protect credit portfolio profitability while balancing approval, delinquency, expected loss, and recovery?**

This question is deliberately multi-dimensional: pulling any single lever (approve more, tighten underwriting, price higher, collect harder) affects the others. The purpose of this project is to build the analytics foundation that lets the company's leadership see those trade-offs instead of guessing at them.

## Symptoms that motivate the question (illustrative, not observed)

These are the *kinds* of symptoms that typically bring a lending business to ask the central question above. They are illustrative of the scenario this project is built around — they are **not** findings, and no data has been analyzed to confirm any of them exist in this project:

- Portfolio growth and delinquency both trending upward at the same time, without it being clear whether growth is *causing* the delinquency increase or is coincidental with it.
- Some loan vintages appear to perform worse than others, but there is no standard vintage-level view to confirm or quantify this.
- Collections results vary across time periods and strategies, without a systematic way to compare recovery performance.
- Approval-rate changes are made periodically (e.g., to hit growth targets), without a standard before/after view of their effect on risk and revenue.

## Executive questions this project is scoped to eventually help answer

1. Is delinquency rising because of new customers, specific vintages, or a shift in overall portfolio mix?
2. Which segments concentrate the most exposure and the most loss?
3. Is higher approval producing profitable growth, or just more volume?
4. Which vintages are deteriorating fastest?
5. How do customers move between "current" and different delinquency buckets over time (roll rates)?
6. How effective are the collections strategies currently in use?
7. If the approval cutoff changed, what would happen to approval volume, risk, and expected result?
8. What should be tracked daily, monthly, and by vintage, and by which stakeholder?

## Decisions these answers are meant to support

- Where the underwriting/approval cutoff should sit.
- Which segments or vintages warrant tightened underwriting, different pricing, or closer monitoring.
- Whether current growth is being achieved profitably.
- Which collections strategies should be scaled up, changed, or retired.
- What belongs on a recurring (daily/monthly/vintage) monitoring cadence, and who owns each metric.

None of these decisions are made by this project. This phase defines the questions; later phases build the ability to answer them with evidence.

## Preliminary hypotheses (explicitly hypotheses — not findings)

Everything in this section is an **unverified hypothesis**, stated here so that later phases have something concrete to test against real (public + synthetic) data. None of these has been checked against any dataset. They must not be treated as conclusions, and they are not repeated as fact anywhere else in this project's documentation.

- **H1**: Recent vintages may show earlier or higher delinquency than older vintages (a vintage effect), rather than delinquency being uniform across the book.
- **H2**: A portfolio-wide delinquency increase may be driven more by mix shift (more originations in higher-risk segments) than by uniform deterioration across all segments.
- **H3**: There may be a trade-off where an approval-rate increase raises volume but also raises the portfolio's blended risk enough to offset some of the revenue gain.
- **H4**: Early delinquency (e.g., first payment default) may be disproportionately concentrated in a small number of segments rather than spread evenly.
- **H5**: Collections strategy effectiveness may vary meaningfully by how early it is applied relative to the delinquency bucket.

## Initial problem tree (illustrative structure, not a diagnosis)

```text
Portfolio profitability at risk
├── Revenue side
│   ├── Approval volume too low or too high relative to risk appetite
│   ├── Pricing not aligned with risk segment
│   └── Portfolio mix shifting toward lower-margin segments
├── Risk side
│   ├── Delinquency rising in specific vintages
│   ├── Delinquency rising in specific segments
│   └── Underwriting policy not adapting to portfolio drift
└── Recovery side
    ├── Cure rates lower than expected in early delinquency
    ├── Collections strategy not matched to delinquency stage
    └── Write-off rate rising faster than provisioning assumes
```

This tree is a structure for organizing future investigation. It is not a result of any investigation performed so far.

## Required separation: description, diagnosis, forecast, decision

This project explicitly separates four categories of analytical statement, and later phases must keep them labeled accordingly rather than blending them:

| Category | What it answers | Example (illustrative only) | What it requires |
|---|---|---|---|
| **Description** | What happened? | "DPD 30 delinquency was X% last month." | Correctly computed, validated KPI from real (or synthetic) data |
| **Diagnosis** | Why did it happen? | "Delinquency rose mainly in vintage Y." | Description + a comparison/decomposition, still correlational |
| **Forecast** | What will happen if nothing changes? | "At the current trend, delinquency reaches Z by month N." | A stated, testable model with documented assumptions and error |
| **Decision** | What should we do? | "Tighten the cutoff for segment S." | Diagnosis or forecast **plus** an explicit business trade-off judgment, owned by a stakeholder, not by the model |

**Rule enforced throughout this project: a hypothesis is never presented as a finding, a correlation is never presented as a causal diagnosis without an explicit causal-inference method and its limitations stated, and a forecast is never presented as a decision.** Where this project's later phases produce a model or a number, the phase's documentation must state which of these four categories it belongs to.
