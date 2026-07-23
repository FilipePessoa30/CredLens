# Project Charter

## Context

CredLens is a portfolio project built around a **fictional** digital credit company. The company originates unsecured consumer loans, holds them on its own balance sheet, and has to manage the tension between approving more applicants, controlling delinquency, pricing risk correctly, and recovering value from loans that go bad. No real company, real customer, or real dataset is represented by this scenario. It exists to give an otherwise-abstract analytics build a coherent, decision-shaped narrative — see `docs/assumptions_and_limitations.md` for what this project explicitly cannot claim.

## Problem

Credit portfolio management involves several teams (risk, credit, collections, finance, product) that each see a slice of the same underlying portfolio, often through different tools, different definitions, and different refresh cycles. Without a shared, versioned, testable analytics layer, two structural problems tend to appear:

1. **Metric disagreement** — "delinquency rate" or "approval rate" computed slightly differently by two teams, producing different numbers for what should be the same fact.
2. **Slow, ad hoc answers** — questions like "which vintage is deteriorating?" require a manual, one-off pull each time, instead of a reusable model anyone can query.

## Objective

Build a reproducible, tested, end-to-end analytics project that demonstrates how these problems are solved in practice: a documented KPI layer, a modeled SQL warehouse, portfolio/vintage/risk analysis, and (in later phases) a simple policy simulator and dashboard — all built incrementally, with each phase's output validated before the next begins.

## Value proposition

For a portfolio reviewer (recruiter, hiring manager, technical interviewer), CredLens is evidence — not a claim — that its author can:

- Translate a vague business tension ("grow the portfolio" vs. "control losses") into specific, well-defined KPIs with explicit formulas and grains.
- Design a data architecture (ingestion → quality → modeling → analytics → presentation) and justify each layer's technology choice.
- Write production-shaped code: typed, tested, linted, documented, and running in CI — not a single notebook.
- Separate description, diagnosis, forecast, and decision instead of blending them into vague "insights."
- Be explicit about what the work does *not* prove, rather than overstating it.

## Target audience

Recruiters and hiring managers in data analytics, BI, data engineering, and risk/credit roles at fintechs, digital banks, and lending/collections operations; technical interviewers evaluating applied SQL, Python, and analytics-engineering skill; peers evaluating the project as a template for their own portfolio work.

## Stakeholders

See `docs/stakeholder_map.md` for the full breakdown. Summary: executive leadership, risk management, credit/underwriting, collections, finance, product, operations, data & technology, and audit/governance — each with a distinct decision this project is meant to eventually support.

## Decisions this product intends to support (future phases)

- Where to set (or move) the approval cutoff.
- Which segments or vintages need tightened underwriting or intensified collections.
- Whether portfolio growth is translating into profitable growth or just volume.
- Which collections strategies are recovering value effectively.
- What should be monitored daily, monthly, and by vintage, and by whom.

None of these decisions are made in the current (foundation) phase. This phase only defines the questions and the scaffolding needed to eventually answer them.

## Future deliverables

1. An audited, licensed data foundation (public data + a documented reproducible synthetic operational layer).
2. A dimensionally modeled SQL warehouse (dbt + DuckDB) with tests on the models themselves.
3. A validated KPI layer computed from that warehouse (not from ad hoc scripts).
4. Portfolio, vintage, and roll-rate analysis.
5. An interpretable probability-of-default model and expected-loss calculation, with documented limitations.
6. A cutoff/policy simulator.
7. A Power BI dashboard and a lightweight demo application.
8. Documentation suitable for both technical and executive audiences.

## Success criteria for this portfolio project

- Each phase is independently reviewable: it runs, is tested, and its scope is honestly represented in its own documentation.
- No phase claims a result it did not actually produce (no invented KPI values, no invented model accuracy, no invented financial impact).
- The project reads as a decision-support tool for a lending business, not as an academic exercise.
- A technical reviewer can clone the repository, follow the README, and reproduce every claim made in it.
- The separation between public data, synthetic data, and (never present) real data stays legible throughout.

## Constraints

- No real personal, customer, or financial data will ever be used.
- No claim of real-world financial impact, model accuracy, or business outcome will be made, because none has been (or will be) produced against a live business.
- Development happens primarily on Windows, so all instructions must remain usable there (with WSL as an option, not a requirement).
- Runtime dependencies are kept minimal by design in the foundation phase; heavier libraries (ML, visualization, databases) are added only when the phase that needs them starts.

## Dependencies

- Availability and licensing terms of candidate public datasets (to be confirmed in the data acquisition phase — see `docs/data_strategy.md`).
- Correct functioning of the local Python toolchain (`uv`, or a documented fallback) across phases.
- No dependency on paid infrastructure, since this is a public portfolio project.

## Risks

| Risk | Type | Mitigation |
|---|---|---|
| Public dataset does not adequately represent a realistic credit portfolio | Data | Document limitations explicitly; supplement with a clearly labeled synthetic layer rather than pretending otherwise |
| Scope creep into "just add one more feature" | Project | Phase gating: each phase has an explicit not-in-scope list, enforced before starting the next |
| Metrics or claims drift toward sounding more definitive than the underlying data supports | Integrity | Explicit `proposed` / `requires_validation` status on every KPI until it is actually computed and reviewed (see `docs/kpi_dictionary.md`) |
| Windows-specific tooling issues block reproducibility | Environment | Validate every documented command in the actual dev environment before claiming it works; document fallbacks |

## Planned phases

See `docs/roadmap.md` for the full, numbered phase list with dependencies and completion criteria. This charter covers **Phase 1: Foundation** only.
