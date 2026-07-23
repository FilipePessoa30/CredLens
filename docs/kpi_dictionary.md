# KPI Dictionary (Preliminary)

This is a **definitions-only** dictionary. No value in this document has been calculated — there is no dataset behind any of these numbers yet (see `docs/data_strategy.md` and `docs/roadmap.md`). Every KPI carries an explicit `status`:

- `proposed` — a working definition exists, consistent with common industry usage, but has not been validated against a specific chosen dataset or stakeholder sign-off.
- `requires_validation` — the concept is standard in credit risk, but the *exact* formula, bucket boundaries, or regulatory framing varies across institutions and jurisdictions; the definition below is a reasonable starting point, not a claimed regulatory standard, and must be confirmed before being treated as final.

No formula below should be read as a mandated regulatory definition. Where regulatory concepts are referenced (e.g., PD/LGD/EAD under Basel-style frameworks), that is only to explain the term in familiar language — this project makes no claim of regulatory compliance or certification.

## Index

Origination: [Application Volume](#application-volume) · [Approval Rate](#approval-rate) · [Booking Rate](#booking-rate)

Portfolio: [Portfolio Balance](#portfolio-balance) · [Average Ticket](#average-ticket)

Delinquency: [Delinquency Rate](#delinquency-rate) · [Days Past Due](#days-past-due-dpd) · [DPD 30 / 60 / 90](#dpd-30-dpd-60-dpd-90) · [First Payment Default](#first-payment-default-fpd)

Vintage & transitions: [Vintage Delinquency](#vintage-delinquency) · [Roll Rate](#roll-rate) · [Cure Rate](#cure-rate)

Recovery: [Recovery Rate](#recovery-rate) · [Write-off Rate](#write-off-rate)

Risk: [Probability of Default (PD)](#probability-of-default-pd) · [Exposure at Default (EAD)](#exposure-at-default-ead) · [Loss Given Default (LGD)](#loss-given-default-lgd) · [Expected Loss (EL)](#expected-loss-el)

Financial: [Revenue](#revenue) · [Cost of Funds](#cost-of-funds) · [Contribution Margin](#contribution-margin) · [Risk-Adjusted Return](#risk-adjusted-return)

Concentration: [Concentration Indicators](#concentration-indicators)

---

### Application Volume

- **Description**: Number of credit applications received in a period. The top-of-funnel origination metric.
- **Conceptual formula**: `COUNT(applications)`
- **Numerator**: Count of applications submitted.
- **Denominator**: N/A (a count, not a ratio).
- **Unit**: Applications (count).
- **Granularity**: Application-level, aggregable to any dimension below.
- **Periodicity**: Daily, monthly.
- **Dimensions**: Channel, product, segment, region.
- **Stakeholder**: Product, Operations, Executive leadership.
- **Pitfalls**: Duplicate applications from the same applicant can inflate volume; needs a de-duplication rule agreed with Product before this is trustworthy.
- **Status**: `proposed`

### Approval Rate

- **Description**: Share of applications approved by underwriting.
- **Conceptual formula**: `Approved Applications / Total Applications`
- **Numerator**: Count of applications approved in the period.
- **Denominator**: Count of applications decisioned in the period.
- **Unit**: Percentage.
- **Granularity**: Application-level, aggregable.
- **Periodicity**: Daily, monthly.
- **Dimensions**: Channel, product, segment, score band, policy version.
- **Stakeholder**: Credit/underwriting, Executive leadership.
- **Pitfalls**: Sensitive to the decisioning window used (same-day vs. eventual decision); comparing across policy changes without segmenting by policy version misattributes cause.
- **Status**: `proposed`

### Booking Rate

- **Description**: Share of approved applications that convert into a funded (booked) loan.
- **Conceptual formula**: `Booked Loans / Approved Applications`
- **Numerator**: Count of loans booked/funded.
- **Denominator**: Count of applications approved in the same cohort/period.
- **Unit**: Percentage.
- **Granularity**: Application/loan-level.
- **Periodicity**: Monthly.
- **Dimensions**: Channel, product, segment.
- **Stakeholder**: Product, Operations, Credit.
- **Pitfalls**: Time lag between approval and booking can straddle period boundaries; needs a cohort-based (not calendar-period) calculation to avoid distortion.
- **Status**: `proposed`

### Portfolio Balance

- **Description**: Total outstanding principal (and, if defined separately, accrued interest) across all active loans at a point in time.
- **Conceptual formula**: `SUM(outstanding_balance)` across active loans.
- **Numerator**: Sum of outstanding balances.
- **Denominator**: N/A (a stock measure, not a ratio).
- **Unit**: Currency.
- **Granularity**: Loan-level, aggregable.
- **Periodicity**: Daily snapshot, reported monthly.
- **Dimensions**: Product, segment, vintage, delinquency bucket.
- **Stakeholder**: Executive leadership, Finance, Risk.
- **Pitfalls**: A stock measure — must not be confused with a flow (e.g., originations); needs a clear "as of" snapshot date and consistent treatment of write-offs (excluded once written off).
- **Status**: `proposed`

### Average Ticket

- **Description**: Average loan amount originated in a period.
- **Conceptual formula**: `SUM(loan_amount) / COUNT(loans)`
- **Numerator**: Sum of originated loan amounts.
- **Denominator**: Count of loans originated.
- **Unit**: Currency.
- **Granularity**: Loan-level, aggregable.
- **Periodicity**: Monthly.
- **Dimensions**: Product, segment, channel.
- **Stakeholder**: Product, Finance.
- **Pitfalls**: Mean is sensitive to outliers; a median or distribution view is often more informative alongside it.
- **Status**: `proposed`

### Delinquency Rate

- **Description**: Share of the portfolio that is past due, at some minimum threshold of days past due.
- **Conceptual formula**: `Balance (or count) of loans with DPD >= threshold / Total portfolio balance (or count)`
- **Numerator**: Balance or count of loans at or beyond the chosen DPD threshold.
- **Denominator**: Total portfolio balance or count.
- **Unit**: Percentage.
- **Granularity**: Loan-level, aggregable.
- **Periodicity**: Daily snapshot, reported monthly.
- **Dimensions**: Product, segment, vintage.
- **Stakeholder**: Risk, Executive leadership, Finance.
- **Pitfalls**: "Delinquency rate" is meaningless without stating the DPD threshold and whether it is balance-weighted or count-weighted — these can tell very different stories. Must always be reported together with its threshold (e.g., "DPD 30+ delinquency rate").
- **Status**: `requires_validation`

### Days Past Due (DPD)

- **Description**: Number of calendar days a loan's payment is overdue relative to its contractual due date.
- **Conceptual formula**: `current_date - contractual_due_date`, for the earliest unpaid installment.
- **Numerator/Denominator**: N/A (a duration measure per loan, not a ratio).
- **Unit**: Days.
- **Granularity**: Loan-level (per installment/obligation).
- **Periodicity**: Daily.
- **Dimensions**: Product, segment, vintage.
- **Stakeholder**: Risk, Collections.
- **Pitfalls**: Grace periods and payment-posting lag (e.g., a payment received but not yet posted) can make DPD appear higher than the borrower's actual behavior; the calculation rule for "days late" must be documented precisely once implemented.
- **Status**: `requires_validation`

### DPD 30, DPD 60, DPD 90

- **Description**: Standard delinquency buckets — loans that are 30+, 60+, or 90+ days past due, respectively. Commonly used as escalating severity thresholds; DPD 90+ is frequently treated as a default proxy, but that mapping is not assumed here without validation.
- **Conceptual formula**: `COUNT or SUM(balance) where DPD >= 30 / 60 / 90`
- **Numerator**: Count or balance of loans meeting the respective threshold.
- **Denominator**: Total portfolio count or balance (when expressed as a rate) — or none, if reported as a raw count/balance.
- **Unit**: Percentage (as a rate) or currency/count (as a stock).
- **Granularity**: Loan-level, aggregable.
- **Periodicity**: Monthly, alongside vintage curves.
- **Dimensions**: Product, segment, vintage.
- **Stakeholder**: Risk, Collections, Executive leadership.
- **Pitfalls**: Bucket boundaries (30/60/90) are conventions, not universal law — some institutions use 1-29/30-59/60-89/90+ style bucketing instead of cumulative thresholds. Must state clearly whether buckets are cumulative ("30+") or discrete ("30-59").
- **Status**: `requires_validation`

### First Payment Default (FPD)

- **Description**: Share of loans where the borrower misses (or is significantly late on) their very first scheduled payment — an early signal of underwriting quality or fraud.
- **Conceptual formula**: `Loans with first installment delinquent (>= threshold DPD) / Loans with a first installment due in the period`
- **Numerator**: Count of loans whose first installment is delinquent past the agreed threshold.
- **Denominator**: Count of loans with a first installment due in the period.
- **Unit**: Percentage.
- **Granularity**: Loan-level.
- **Periodicity**: Monthly, by origination cohort.
- **Dimensions**: Product, segment, channel, vintage.
- **Stakeholder**: Credit/underwriting, Risk.
- **Pitfalls**: Highly sensitive to the chosen DPD threshold and observation window; small cohorts produce noisy rates — needs a minimum cohort size before being reported as meaningful.
- **Status**: `requires_validation`

### Vintage Delinquency

- **Description**: Delinquency rate of a loan cohort (vintage — typically defined by origination month), tracked over the cohort's own age (months on book) rather than calendar time. The standard way to compare "is a newer batch of loans behaving worse than older batches, at the same age?"
- **Conceptual formula**: `Delinquent balance (or count) at age m / Original (or outstanding) cohort balance at age m`, plotted across `m = 0, 1, 2, ...`
- **Numerator**: Delinquent balance/count within the vintage at a given months-on-book.
- **Denominator**: Cohort's originated (or outstanding) balance/count at that same months-on-book.
- **Unit**: Percentage, as a curve over months-on-book.
- **Granularity**: Vintage (origination cohort) level.
- **Periodicity**: Monthly update; typically visualized as vintage curves.
- **Dimensions**: Product, segment.
- **Stakeholder**: Risk, Credit, Executive leadership.
- **Pitfalls**: Comparing vintages at different calendar dates without aligning by months-on-book is the single most common vintage-analysis mistake; immature (young) vintages will structurally look "better" than mature ones simply because they haven't had time to deteriorate yet.
- **Status**: `requires_validation`

### Roll Rate

- **Description**: The rate at which loans move from one delinquency bucket to the next (worse) bucket over a defined period (e.g., from "current" to "DPD 30", or "DPD 30" to "DPD 60").
- **Conceptual formula**: `Loans (or balance) that moved from bucket X to bucket X+1 / Loans (or balance) in bucket X at the start of the period`
- **Numerator**: Balance/count transitioning to the next worse bucket.
- **Denominator**: Balance/count in the origin bucket at period start.
- **Unit**: Percentage, per transition (a full roll-rate matrix has one rate per bucket pair).
- **Granularity**: Loan-level, aggregated into a bucket-transition matrix.
- **Periodicity**: Monthly.
- **Dimensions**: Product, segment.
- **Stakeholder**: Risk, Collections, Finance (feeds provisioning).
- **Pitfalls**: Requires a consistent bucket definition and a consistent snapshot cadence (e.g., strictly monthly) — mixing snapshot frequencies breaks the transition matrix.
- **Status**: `requires_validation`

### Cure Rate

- **Description**: The rate at which delinquent loans return to current status (i.e., "cure") within a defined period, the inverse-direction counterpart to roll rate.
- **Conceptual formula**: `Loans (or balance) that returned to current from bucket X / Loans (or balance) in bucket X at the start of the period`
- **Numerator**: Balance/count curing from a delinquent bucket back to current.
- **Denominator**: Balance/count in that delinquent bucket at period start.
- **Unit**: Percentage.
- **Granularity**: Loan-level, aggregated by bucket.
- **Periodicity**: Monthly.
- **Dimensions**: Product, segment, collections strategy.
- **Stakeholder**: Collections, Risk.
- **Pitfalls**: A "partial cure" (payment made but not enough to return to fully current) needs an explicit rule; otherwise cure rate can be inconsistently computed across periods.
- **Status**: `requires_validation`

### Recovery Rate

- **Description**: Share of the amount owed on defaulted/written-off loans that is ultimately recovered (through collections, sale of collateral if any, or debt sale).
- **Conceptual formula**: `Amount recovered post-default / Amount owed at default (or at write-off)`
- **Numerator**: Cumulative amount recovered after default.
- **Denominator**: Outstanding balance at the point of default or write-off.
- **Unit**: Percentage.
- **Granularity**: Loan-level, aggregable.
- **Periodicity**: Monthly, but typically matured/reported over a longer recovery window (e.g., 12-24 months post-default).
- **Dimensions**: Product, segment, collections strategy, vintage.
- **Stakeholder**: Collections, Finance, Risk.
- **Pitfalls**: Recovery happens over a long tail — reporting a recovery rate too soon after default understates it; needs a stated observation window and treatment of the (often large) share of accounts still "open" for recovery.
- **Status**: `requires_validation`

### Write-off Rate

- **Description**: Share of the portfolio removed from the balance sheet as uncollectible in a period.
- **Conceptual formula**: `Amount written off in period / Average (or beginning) portfolio balance in the period`
- **Numerator**: Balance written off during the period.
- **Denominator**: Average or beginning portfolio balance for the same period.
- **Unit**: Percentage (often annualized).
- **Granularity**: Loan-level, aggregable.
- **Periodicity**: Monthly, often reported as an annualized rate.
- **Dimensions**: Product, segment, vintage.
- **Stakeholder**: Finance, Risk, Executive leadership.
- **Pitfalls**: The write-off policy (e.g., "write off at 180 DPD") directly drives this number — comparing write-off rates across companies or periods with different write-off policies is misleading unless the policy is stated alongside the rate.
- **Status**: `requires_validation`

### Probability of Default (PD)

- **Description**: The estimated likelihood that a loan (or borrower) will default within a defined horizon (e.g., 12 months), commonly used in a Basel-style expected-loss framing. Explained here in familiar risk-modeling language only — no regulatory compliance is claimed or implied.
- **Conceptual formula**: Output of a risk model, `PD = P(default within horizon | borrower/loan characteristics)`; empirically often benchmarked as `Defaulted loans / Total loans in a risk-homogeneous segment, observed over the chosen horizon`.
- **Numerator**: Count of defaults observed in the segment over the horizon (for empirical benchmarking).
- **Denominator**: Count of loans in the segment at the start of the horizon.
- **Unit**: Percentage (a probability).
- **Granularity**: Loan or segment/score-band level.
- **Periodicity**: Model output at origination; monitored/recalibrated periodically (e.g., quarterly).
- **Dimensions**: Score band, product, segment, vintage.
- **Stakeholder**: Risk, Credit.
- **Pitfalls**: Requires a precise, fixed "default" definition and horizon (e.g., "90+ DPD within 12 months") before it means anything comparable across time; a model that is not monitored for drift will silently become miscalibrated. No model exists yet in this project — see `docs/roadmap.md`.
- **Status**: `requires_validation`

### Exposure at Default (EAD)

- **Description**: The estimated outstanding balance at the moment a loan defaults — relevant because balances can change between now and a future default (e.g., through further drawdowns on a revolving product; less relevant for simple fixed-installment loans, but still typically modeled explicitly).
- **Conceptual formula**: `Outstanding balance expected at the time of default` (for installment loans, often approximated by the scheduled outstanding balance at default time).
- **Numerator/Denominator**: N/A (an estimated balance, not a ratio).
- **Unit**: Currency.
- **Granularity**: Loan-level.
- **Periodicity**: Modeled at origination or at each snapshot; used as an input to Expected Loss.
- **Dimensions**: Product, segment.
- **Stakeholder**: Risk, Finance.
- **Pitfalls**: For products without revolving drawdown, EAD is often close to the scheduled balance — treating it as trivially equal to the current balance without checking that assumption is a common shortcut that doesn't hold for all product types.
- **Status**: `requires_validation`

### Loss Given Default (LGD)

- **Description**: The share of exposure that is actually lost after a default, net of recoveries — i.e., `1 - Recovery Rate`, expressed as a modeling input.
- **Conceptual formula**: `1 - (Amount recovered / Exposure at default)`
- **Numerator**: Exposure at default minus amount recovered.
- **Denominator**: Exposure at default.
- **Unit**: Percentage.
- **Granularity**: Loan-level, aggregable to segment.
- **Periodicity**: Modeled periodically; realized value only known after the recovery window closes.
- **Dimensions**: Product, segment, collections strategy.
- **Stakeholder**: Risk, Finance.
- **Pitfalls**: Same long-tail observation problem as Recovery Rate — an LGD computed before recovery has matured will be biased high (i.e., loss overstated).
- **Status**: `requires_validation`

### Expected Loss (EL)

- **Description**: The modeled average loss expected on a loan or portfolio over a horizon, combining the probability of default, the exposure at that point, and the share lost given default.
- **Conceptual formula**: `EL = PD × EAD × LGD`
- **Numerator/Denominator**: N/A (a modeled currency amount, the product of three inputs above).
- **Unit**: Currency (often also expressed as a percentage of exposure).
- **Granularity**: Loan-level, aggregable to portfolio.
- **Periodicity**: Modeled at origination and monitored periodically.
- **Dimensions**: Product, segment, vintage.
- **Stakeholder**: Risk, Finance, Executive leadership.
- **Pitfalls**: Only as reliable as its three inputs — presenting EL with false precision when PD/EAD/LGD are themselves rough estimates overstates confidence; each input's own uncertainty should travel with the EL figure once modeled.
- **Status**: `requires_validation`

### Revenue

- **Description**: Interest and fee income earned from the loan portfolio in a period.
- **Conceptual formula**: `SUM(interest income + fee income)` recognized in the period.
- **Numerator**: Sum of interest and fee income.
- **Denominator**: N/A (a flow measure).
- **Unit**: Currency.
- **Granularity**: Loan-level, aggregable.
- **Periodicity**: Monthly.
- **Dimensions**: Product, segment.
- **Stakeholder**: Finance, Executive leadership.
- **Pitfalls**: Accrual timing matters — interest accrued vs. interest actually collected can diverge meaningfully once delinquency rises; the definition must state which basis is used.
- **Status**: `requires_validation`

### Cost of Funds

- **Description**: The cost the company incurs to fund the loans it originates (e.g., interest paid on debt or deposits funding the portfolio).
- **Conceptual formula**: `SUM(interest expense on funding sources) / Average funded portfolio balance`
- **Numerator**: Interest expense on funding.
- **Denominator**: Average portfolio balance funded in the period.
- **Unit**: Percentage (a rate) or currency (as a total).
- **Granularity**: Portfolio-level (funding is typically not loan-level).
- **Periodicity**: Monthly.
- **Dimensions**: Funding source, product line (if funding is earmarked).
- **Stakeholder**: Finance.
- **Pitfalls**: Blending multiple funding sources with different costs into one rate can obscure which funding is actually marginal for growth decisions.
- **Status**: `requires_validation`

### Contribution Margin

- **Description**: Revenue net of the direct costs of the portfolio (cost of funds and expected/realized credit losses), before allocating shared overhead.
- **Conceptual formula**: `Revenue - Cost of Funds - Credit Losses (expected or realized)`
- **Numerator/Denominator**: N/A (a currency amount, or expressed as a percentage of revenue/balance).
- **Unit**: Currency, or percentage of revenue or portfolio balance.
- **Granularity**: Portfolio-level, aggregable by segment/product.
- **Periodicity**: Monthly.
- **Dimensions**: Product, segment.
- **Stakeholder**: Finance, Executive leadership.
- **Pitfalls**: Whether "credit losses" here means expected loss (modeled) or realized write-offs (actual) changes the number and the story substantially — must be stated explicitly each time this is reported.
- **Status**: `requires_validation`

### Risk-Adjusted Return

- **Description**: A profitability measure that accounts for the risk taken to earn it, allowing comparison across segments with different risk profiles on a like-for-like basis.
- **Conceptual formula**: `Contribution Margin / Economic Capital (or another risk-weighted exposure measure)` — the exact denominator convention (e.g., RAROC-style) is an open design decision, not fixed here.
- **Numerator**: Contribution margin (or a similarly risk-net profitability measure).
- **Denominator**: A risk-weighted capital or exposure measure (method to be selected and validated).
- **Unit**: Percentage.
- **Granularity**: Segment or portfolio-level.
- **Periodicity**: Monthly or quarterly.
- **Dimensions**: Product, segment.
- **Stakeholder**: Executive leadership, Finance, Risk.
- **Pitfalls**: The most methodologically open KPI in this dictionary — there is no single universal formula, and picking one implicitly makes a risk-appetite statement. Must be selected deliberately, not defaulted into.
- **Status**: `requires_validation`

### Concentration Indicators

- **Description**: Measures of how concentrated the portfolio's exposure or loss is in a small number of segments, vintages, or borrowers — relevant because concentrated risk behaves differently (and more dangerously) than diversified risk.
- **Conceptual formula**: Multiple candidate measures, e.g., share of exposure held by the top N segments/borrowers, or a Herfindahl-Hirschman-style index: `HHI = SUM(segment_share_i ^ 2)`.
- **Numerator/Denominator**: Depends on the chosen measure (see above).
- **Unit**: Percentage (top-N share) or an index value (HHI, unitless, 0-1 or 0-10000 by convention).
- **Granularity**: Segment, vintage, or borrower-level, rolled up to portfolio.
- **Periodicity**: Monthly or quarterly.
- **Dimensions**: Segment, product, geography (if available).
- **Stakeholder**: Risk, Executive leadership, Audit/Governance.
- **Pitfalls**: The choice of "segment" definition drives the result — a portfolio can look diversified by product but concentrated by underlying borrower risk profile; more than one concentration lens is usually needed.
- **Status**: `requires_validation`
