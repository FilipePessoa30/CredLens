# Stakeholder Map

For each stakeholder group, this map records: the decision they own, the question they need answered, the indicator(s) that inform it, how often they need it, the level of detail they need it at, and the analytical product that would plausibly serve them. This is planning input for future phases — none of these indicators are computed yet (see `docs/kpi_dictionary.md` for definitions and status).

## Executive leadership (CEO / board)

- **Decision**: Overall growth vs. risk appetite trade-off; capital allocation to lending.
- **Question**: Is the portfolio growing profitably, and is risk within appetite?
- **Indicators**: Portfolio balance, approval rate, delinquency rate, expected loss, risk-adjusted return.
- **Periodicity**: Monthly, with a quarterly deep dive.
- **Granularity**: Portfolio-level, with segment-level drill-down available on demand.
- **Possible analytical product**: Executive summary dashboard (Power BI) with a small set of headline KPIs and trend lines.

## Risk management

- **Decision**: Risk appetite thresholds; where to flag concentration or emerging deterioration.
- **Question**: Where is risk concentrating, and is it trending in a direction that requires action?
- **Indicators**: PD, LGD, EAD, expected loss, concentration indicators, vintage delinquency, roll rate.
- **Periodicity**: Monthly, with ad hoc investigation capability.
- **Granularity**: Segment, vintage, and product-level.
- **Possible analytical product**: Risk dashboard with vintage curves and concentration views; underlying warehouse queryable for ad hoc investigation.

## Credit / underwriting

- **Decision**: Where to set (or adjust) the approval cutoff and underwriting policy.
- **Question**: What would happen to approval volume, risk, and expected result if the cutoff moved?
- **Indicators**: Approval rate, booking rate, first payment default, PD by score band.
- **Periodicity**: Monthly for monitoring; on demand when a policy change is proposed.
- **Granularity**: Score band / segment-level.
- **Possible analytical product**: Cutoff / policy simulator (future phase) built on top of the risk model.

## Collections

- **Decision**: Which collections strategy to apply to which delinquency bucket/segment.
- **Question**: How effective is each collections strategy at recovering value, and how quickly?
- **Indicators**: Roll rate, cure rate, recovery rate, write-off rate, DPD buckets (30/60/90).
- **Periodicity**: Weekly operationally; monthly for strategy review.
- **Granularity**: Delinquency bucket and strategy/segment-level.
- **Possible analytical product**: Collections performance view — recovery curves by strategy and bucket.

## Finance

- **Decision**: Provisioning, funding needs, profitability reporting.
- **Question**: What is the portfolio's contribution margin and risk-adjusted return, and how is it trending?
- **Indicators**: Revenue, cost of funds, contribution margin, expected loss, write-off rate, risk-adjusted return.
- **Periodicity**: Monthly, aligned to financial close.
- **Granularity**: Portfolio-level, with product-line breakdown.
- **Possible analytical product**: Profitability view reconciling risk metrics with financial statements.

## Product

- **Decision**: Product design and eligibility rules (loan amount, term, pricing tiers).
- **Question**: How do different product configurations perform in terms of approval, uptake, and risk?
- **Indicators**: Application volume, approval rate, average ticket, delinquency rate by product configuration.
- **Periodicity**: Monthly, or tied to product experiment cycles.
- **Granularity**: Product / offer-level.
- **Possible analytical product**: Product performance comparison view.

## Operations

- **Decision**: Staffing and process allocation for origination and servicing workflows.
- **Question**: Where are volume and workload concentrated, and is turnaround time acceptable?
- **Indicators**: Application volume, booking rate, processing/turnaround indicators (future scope).
- **Periodicity**: Weekly.
- **Granularity**: Channel / process-step level.
- **Possible analytical product**: Operational volume and throughput view.

## Data & technology

- **Decision**: What gets built, in what order, and to what quality bar; data platform investment.
- **Question**: Is the data foundation reliable, tested, and fit for the analytics being built on top of it?
- **Indicators**: Data quality check pass rate, pipeline freshness, test coverage of models (future scope).
- **Periodicity**: Continuous (CI) plus periodic architecture review.
- **Granularity**: Pipeline / model-level.
- **Possible analytical product**: Data quality and pipeline health monitoring (future phase).

## Audit / governance

- **Decision**: Whether controls, documentation, and model governance are adequate for the risk being taken.
- **Question**: Can every reported number be traced to its source and method? Is model risk documented?
- **Indicators**: Documentation completeness, lineage/traceability, model assumptions and limitations register.
- **Periodicity**: Periodic review (e.g., quarterly) plus on-demand audit.
- **Granularity**: Process and model-level, not just output-level.
- **Possible analytical product**: This documentation set itself (charter, KPI dictionary, assumptions & limitations) plus lineage notes in the future warehouse layer.
