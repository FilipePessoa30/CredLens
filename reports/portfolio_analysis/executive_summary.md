# Case Study: CredLens Synthetic Credit Portfolio

**All figures below describe a fully synthetic data-generation process (DGP), not a real financial institution.**

Build: `BUILD_kpi_test` | Suite: `SUITE_sample_2026` | Analytical fingerprint: `a891dff7f62b3ff4...`

## 1. Context

CredLens is a portfolio project simulating a Brazilian digital credit fintech. This analysis uses the counterfactual scenario suite (baseline, policy expansion, policy tightening, macroeconomic stress, collections change) built on a DuckDB + dbt warehouse.

## 2. Key findings

> **Question:** What happens to approvals and risk if the approval score cutoff is relaxed (policy_expansion)?
>
> **Evidence:** approval_rate 57.43% -> 88.32% (delta 30.89%); write-offs 51 -> 82. Of the 2935 contracts booked in both runs, PAR90 was 5.61%; the 2384 marginal contracts expansion added had PAR90 6.84%.
>
> **Interpretation:** Within this synthetic scenario, relaxing the cutoff increased approvals and added a population of marginal contracts with measurably higher risk than the shared population - exactly the mechanism a real policy relaxation would be expected to trigger.
>
> **Decision this could support:** Would inform a discussion about the volume/risk trade-off of a cutoff change - NOT a profitability conclusion (no revenue/cost data exists in this DGP).
>
> **Risk/limitation:** Synthetic DGP only; approval-score mechanics are simplified vs. a real underwriting model.

> **Question:** Does a macroeconomic shock affect the portfolio, and only after it happens?
>
> **Evidence:** Pre-shock PAR90 delta (stress - baseline): 0.00% (should be ~0). Post-shock PAR90 delta: 5.59%.
>
> **Interpretation:** The DGP's pre-shock identity guarantee holds empirically in this build - baseline and stress are indistinguishable before the shock date, and diverge measurably after it.
>
> **Decision this could support:** Supports treating the shock's effect as isolated to the post-shock period when reasoning about this scenario.
>
> **Risk/limitation:** One suite/seed; see the multi-seed section of the technical report for robustness across seeds.

> **Question:** Does intensifying collections activity change outcomes, and can that be attributed to individual contacts?
>
> **Evidence:** approval_rate delta: 0.00% (expected ~0, collections_change does not touch approval); write-off count delta: -34.
>
> **Interpretation:** collections_change only varies AGGREGATE, scenario-level parameters in this DGP - there is no per-contact causal link recorded.
>
> **Decision this could support:** Cannot support a claim about which specific collections action caused which outcome.
>
> **Risk/limitation:** Explicitly NOT causal evidence for any individual collections strategy - see limitations.

> **Question:** How much was written off vs. recovered across scenarios in this build?
>
> **Evidence:** Total write-off: R$ 1,462,751.07; total recovery: R$ 21,587.07 (1.48% recovery rate).
>
> **Interpretation:** Recovery rate reflects the DGP's own configured recovery-probability/amount rule, not a real collections operation's performance.
>
> **Decision this could support:** Illustrates the shape of a write-off/recovery KPI dashboard, not a real recovery estimate.
>
> **Risk/limitation:** No LGD/EAD modeling - recovery_rate here is a DGP configuration outcome.

## 3. Risks and limitations

- Every figure is synthetic; no claim of real-institution representativeness.
- No revenue, cost, LGD, EAD, or regulatory PD data exists in this DGP.
- `collections_change` must never be read as causal evidence of an individual action.
- Scenario comparisons are only valid within the same suite (same seed/CRN).

## 4. Next steps

- An interactive dashboard (out of scope this phase).
- A trained predictive risk model (out of scope this phase).
