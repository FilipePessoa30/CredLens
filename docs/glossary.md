# Glossary

Plain-language definitions of banking and analytics terms used throughout this project. For KPI-specific formulas, grains, and caveats, see `docs/kpi_dictionary.md` — this glossary explains the concept in words; the dictionary defines how it would be measured.

## Credit and lending terms

- **Applicant / Borrower** — A person or entity who has submitted a credit application (applicant) or who holds an active loan (borrower).
- **Origination** — The process of a loan being approved and funded; "originations" refers to the loans created in a given period.
- **Underwriting** — The process (rules and/or models) used to decide whether to approve an application and on what terms.
- **Cutoff (approval cutoff)** — A threshold (often a risk score) above or below which applications are approved or declined.
- **Booking** — The act of a loan actually being funded/disbursed after approval; not every approved application is booked.
- **Vintage** — A cohort of loans grouped by origination period (commonly origination month), analyzed by their own age ("months on book") rather than by calendar date, so cohorts can be compared fairly.
- **Delinquency** — The state of a loan being behind on its contractual payment schedule.
- **Days Past Due (DPD)** — How many days overdue a loan's earliest unpaid installment is.
- **Delinquency bucket** — A discretized range of DPD (e.g., "current", "1-29", "30-59", "60-89", "90+") used to categorize how late a loan is.
- **Roll rate** — The rate at which loans move from one delinquency bucket into the next, worse bucket over a period.
- **Cure** — A delinquent loan returning to current status.
- **Default** — A loan reaching a contractually or institutionally defined state of serious non-payment (the specific threshold, e.g., 90+ DPD, must be defined explicitly wherever used — see `docs/kpi_dictionary.md`).
- **First Payment Default (FPD)** — A loan defaulting (or becoming seriously delinquent) on its very first scheduled payment — often used as an early underwriting-quality or fraud signal.
- **Write-off (charge-off)** — Removing a loan's balance from the balance sheet as uncollectible, per a defined policy (e.g., "write off at 180 DPD").
- **Recovery** — Money collected on a loan after it has defaulted or been written off (via collections, collateral, or debt sale).
- **Collections** — The operational function (and its strategies) responsible for recovering payment from delinquent or defaulted borrowers.

## Risk modeling terms

- **Probability of Default (PD)** — The estimated likelihood that a loan or borrower defaults within a given time horizon.
- **Exposure at Default (EAD)** — The estimated outstanding balance at the moment a loan defaults.
- **Loss Given Default (LGD)** — The share of exposure actually lost after default, net of recoveries (`1 - recovery rate`).
- **Expected Loss (EL)** — The modeled average loss expected on a loan or portfolio, calculated as `PD × EAD × LGD`.
- **Score band** — A grouping of applicants/loans by ranges of a risk score, used to analyze or apply policy at a coarser grain than individual scores.
- **Segment** — Any grouping of applicants, loans, or the portfolio used for analysis (e.g., by product, channel, risk band, geography).
- **Concentration risk** — The risk that a large share of exposure or loss is concentrated in a small number of segments, vintages, or borrowers, rather than diversified.
- **Data drift** — Change over time in the statistical properties of a model's input data, which can silently degrade model performance.
- **Concept drift** — Change over time in the actual relationship between a model's inputs and the outcome it predicts.

## Financial terms

- **Portfolio balance** — The total outstanding principal (and, if defined, accrued interest) across active loans at a point in time.
- **Revenue (in this context)** — Interest and fee income earned from the loan portfolio.
- **Cost of funds** — The cost incurred to fund the loans the company originates.
- **Contribution margin** — Revenue net of the direct costs of the portfolio (cost of funds and credit losses), before shared overhead.
- **Risk-adjusted return** — A profitability measure that accounts for the risk taken to earn it, enabling fair comparison across segments with different risk profiles.
- **Provisioning** — Setting aside reserves against expected future credit losses, informed by expected-loss modeling.

## Data and analytics-engineering terms

- **Grain (of a table or metric)** — The level of detail one row represents (e.g., "one row per loan per month"); getting the grain wrong is a common source of double-counting or under-counting errors.
- **Dimensional modeling** — A data modeling approach (facts and dimensions) optimized for analytical querying, as opposed to transactional systems design.
- **Staging model (dbt)** — A transformation step that cleans and standardizes raw source data with minimal business logic.
- **Mart (dbt)** — A transformation step that applies business logic to produce analysis-ready, typically wide, tables for a specific domain.
- **Data quality check** — An automated validation (e.g., schema, type, range, referential) that raw or transformed data must pass before being trusted downstream.
- **Lineage** — The traceable path from a reported number back to the source data and transformation logic that produced it.
- **Synthetic data** — Data generated by code according to documented rules, used here to fill structural gaps that public datasets don't cover (see `docs/data_strategy.md`); never presented as an observed real-world outcome.
