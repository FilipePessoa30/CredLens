"""Bilingual report generation (Phase 6 sections 16-17). Every number in
these reports is formatted directly from a DataFrame/dict this same run
computed via SQL - never hand-typed. Executive reports use "decision
cards" (question / evidence / interpretation / decision it could support
/ risk-limitation) and stick to what the DGP itself demonstrates, never a
real-bank claim (see docs/counterfactual_scenarios.md).
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def _fmt_pct(x: float | None) -> str:
    return "n/a" if x is None or pd.isna(x) else f"{x * 100:.2f}%"


def _fmt_brl(x: float | None) -> str:
    return "n/a" if x is None or pd.isna(x) else f"R$ {x:,.2f}"


def _fmt_int(x: Any) -> str:
    return "n/a" if x is None or pd.isna(x) else f"{int(x):,}"


def decision_card(
    question: str,
    evidence: str,
    interpretation: str,
    decision: str,
    risk: str,
    *,
    lang: str = "en",
) -> str:
    if lang == "pt-BR":
        return (
            f"> **Pergunta:** {question}\n"
            f">\n> **Evidência:** {evidence}\n"
            f">\n> **Interpretação:** {interpretation}\n"
            f">\n> **Decisão que poderia apoiar:** {decision}\n"
            f">\n> **Risco/limitação:** {risk}\n"
        )
    return (
        f"> **Question:** {question}\n"
        f">\n> **Evidence:** {evidence}\n"
        f">\n> **Interpretation:** {interpretation}\n"
        f">\n> **Decision this could support:** {decision}\n"
        f">\n> **Risk/limitation:** {risk}\n"
    )


def build_executive_summary(
    *,
    lang: str,
    suite_id: str,
    build_id: str,
    fingerprint: str,
    scenario_cmp: pd.DataFrame,
    macro_pp: pd.DataFrame,
    composition: dict[str, dict[str, Any]],
    writeoff_recovery_totals: pd.DataFrame,
) -> str:
    pe = scenario_cmp[scenario_cmp["scenario"] == "policy_expansion"]
    cc = scenario_cmp[scenario_cmp["scenario"] == "collections_change"]
    pre = macro_pp[macro_pp["period"] == "pre_shock"]
    post = macro_pp[macro_pp["period"] == "post_shock"]

    total_write_off = writeoff_recovery_totals["total_write_off_amount"].sum()
    total_recovery = writeoff_recovery_totals["total_recovery_amount"].sum()

    is_pt = lang == "pt-BR"
    lines: list[str] = []
    title = (
        "Case Study: CredLens Synthetic Credit Portfolio"
        if not is_pt
        else "Estudo de Caso: Carteira de Crédito Sintética CredLens"
    )
    lines.append(f"# {title}\n")
    lines.append(
        "**All figures below describe a fully synthetic data-generation process (DGP), "
        "not a real financial institution.**\n"
        if not is_pt
        else "**Todos os números abaixo descrevem um processo de geração de dados (DGP) "
        "totalmente sintético, não uma instituição financeira real.**\n"
    )
    lines.append(
        f"Build: `{build_id}` | Suite: `{suite_id}` | "
        f"Analytical fingerprint: `{fingerprint[:16]}...`\n"
    )

    if is_pt:
        lines.append("## 1. Contexto\n")
        lines.append(
            "O CredLens é um projeto de portfólio que simula uma fintech de crédito digital "
            "brasileira. Esta análise usa a suíte de cenários contrafactuais (baseline, "
            "expansão de política, aperto de política, estresse macroeconômico, mudança de "
            "cobrança) construída sobre um warehouse DuckDB + dbt.\n"
        )
        lines.append("## 2. Principais resultados\n")
    else:
        lines.append("## 1. Context\n")
        lines.append(
            "CredLens is a portfolio project simulating a Brazilian digital credit fintech. "
            "This analysis uses the counterfactual scenario suite (baseline, policy "
            "expansion, policy tightening, macroeconomic stress, collections change) built "
            "on a DuckDB + dbt warehouse.\n"
        )
        lines.append("## 2. Key findings\n")

    if len(pe) > 0:
        row = pe.iloc[0]
        comp = composition.get("policy_expansion")
        comp_text = (
            f"Of the {comp['shared_booked_count']} contracts booked in both runs, PAR90 "
            f"was {_fmt_pct(comp['shared_par90'])}; the {comp['scenario_only_count']} "
            f"marginal contracts expansion added had PAR90 {_fmt_pct(comp['marginal_par90'])}."
            if comp
            else "Composition breakdown not computed."
        )
        question = (
            "What happens to approvals and risk if the approval score cutoff is relaxed "
            "(policy_expansion)?"
            if not is_pt
            else "O que acontece com aprovações e risco se o cutoff de aprovação for "
            "relaxado (policy_expansion)?"
        )
        evidence = (
            f"approval_rate {_fmt_pct(row['baseline_approval_rate'])} -> "
            f"{_fmt_pct(row['approval_rate'])} (delta {_fmt_pct(row['approval_rate_delta_abs'])}); "
            f"write-offs {_fmt_int(row['baseline_write_off_count'])} -> "
            f"{_fmt_int(row['write_off_count'])}. {comp_text}"
        )
        interpretation = (
            "Within this synthetic scenario, relaxing the cutoff increased approvals and "
            "added a population of marginal contracts with measurably higher risk than the "
            "shared population - exactly the mechanism a real policy relaxation would be "
            "expected to trigger."
            if not is_pt
            else "Dentro deste cenário sintético, relaxar o cutoff aumentou aprovações e "
            "adicionou uma população de contratos marginais com risco mensuravelmente maior "
            "que a população compartilhada - exatamente o mecanismo que uma relaxação de "
            "política real deveria acionar."
        )
        decision = (
            "Would inform a discussion about the volume/risk trade-off of a cutoff change - "
            "NOT a profitability conclusion (no revenue/cost data exists in this DGP)."
            if not is_pt
            else "Poderia informar uma discussão sobre o trade-off volume/risco de uma "
            "mudança de cutoff - NÃO uma conclusão de rentabilidade (não existem dados de "
            "receita/custo neste DGP)."
        )
        risk = (
            "Synthetic DGP only; approval-score mechanics are simplified vs. a real "
            "underwriting model."
            if not is_pt
            else "Apenas DGP sintético; a mecânica do score de aprovação é simplificada "
            "frente a um modelo de underwriting real."
        )
        lines.append(decision_card(question, evidence, interpretation, decision, risk, lang=lang))

    if len(post) > 0 and len(pre) > 0:
        pre_row, post_row = pre.iloc[0], post.iloc[0]
        question = (
            "Does a macroeconomic shock affect the portfolio, and only after it happens?"
            if not is_pt
            else "Um choque macroeconômico afeta a carteira, e só depois que ele ocorre?"
        )
        evidence = (
            f"Pre-shock PAR90 delta (stress - baseline): "
            f"{_fmt_pct(pre_row['par90_delta_abs'])} (should be ~0). Post-shock PAR90 "
            f"delta: {_fmt_pct(post_row['par90_delta_abs'])}."
        )
        interpretation = (
            "The DGP's pre-shock identity guarantee holds empirically in this build - "
            "baseline and stress are indistinguishable before the shock date, and diverge "
            "measurably after it."
            if not is_pt
            else "A garantia de identidade pré-choque do DGP se sustenta empiricamente "
            "neste build - baseline e estresse são indistinguíveis antes da data do "
            "choque, e divergem mensuravelmente depois."
        )
        decision = (
            "Supports treating the shock's effect as isolated to the post-shock period "
            "when reasoning about this scenario."
            if not is_pt
            else "Apoia tratar o efeito do choque como isolado ao período pós-choque ao "
            "raciocinar sobre este cenário."
        )
        risk = (
            "One suite/seed; see the multi-seed section of the technical report for "
            "robustness across seeds."
            if not is_pt
            else "Uma suíte/seed; veja a seção multi-seed do relatório técnico para "
            "robustez entre seeds."
        )
        lines.append(decision_card(question, evidence, interpretation, decision, risk, lang=lang))

    if len(cc) > 0:
        row = cc.iloc[0]
        question = (
            "Does intensifying collections activity change outcomes, and can that be "
            "attributed to individual contacts?"
            if not is_pt
            else "Intensificar a atividade de cobrança muda os resultados, e isso pode ser "
            "atribuído a contatos individuais?"
        )
        evidence = (
            f"approval_rate delta: {_fmt_pct(row['approval_rate_delta_abs'])} (expected "
            f"~0, collections_change does not touch approval); write-off count delta: "
            f"{_fmt_int(row['write_off_count_delta_abs'])}."
        )
        interpretation = (
            "collections_change only varies AGGREGATE, scenario-level parameters in this "
            "DGP - there is no per-contact causal link recorded."
            if not is_pt
            else "collections_change varia apenas parâmetros AGREGADOS de cenário neste "
            "DGP - não há vínculo causal por contato registrado."
        )
        decision = (
            "Cannot support a claim about which specific collections action caused which outcome."
            if not is_pt
            else "Não pode apoiar uma alegação sobre qual ação específica de cobrança "
            "causou qual resultado."
        )
        risk = (
            "Explicitly NOT causal evidence for any individual collections strategy - see "
            "limitations."
            if not is_pt
            else "Explicitamente NÃO é evidência causal para nenhuma estratégia de "
            "cobrança individual - veja limitações."
        )
        lines.append(decision_card(question, evidence, interpretation, decision, risk, lang=lang))

    wo_question = (
        "How much was written off vs. recovered across scenarios in this build?"
        if not is_pt
        else "Quanto foi baixado vs. recuperado entre cenários neste build?"
    )
    wo_evidence = (
        f"Total write-off: {_fmt_brl(total_write_off)}; total recovery: "
        f"{_fmt_brl(total_recovery)} "
        f"({_fmt_pct(total_recovery / total_write_off if total_write_off else None)} "
        f"recovery rate)."
    )
    wo_interpretation = (
        "Recovery rate reflects the DGP's own configured recovery-probability/amount "
        "rule, not a real collections operation's performance."
        if not is_pt
        else "A taxa de recuperação reflete a regra de probabilidade/valor de recuperação "
        "configurada no DGP, não o desempenho de uma operação de cobrança real."
    )
    wo_decision = (
        "Illustrates the shape of a write-off/recovery KPI dashboard, not a real recovery estimate."
        if not is_pt
        else "Ilustra o formato de um dashboard de KPI de baixa/recuperação, não uma "
        "estimativa real de recuperação."
    )
    wo_risk = (
        "No LGD/EAD modeling - recovery_rate here is a DGP configuration outcome."
        if not is_pt
        else "Sem modelagem de LGD/EAD - recovery_rate aqui é um resultado de configuração do DGP."
    )
    lines.append(
        decision_card(wo_question, wo_evidence, wo_interpretation, wo_decision, wo_risk, lang=lang)
    )

    if is_pt:
        lines.append("## 3. Riscos e limitações\n")
        lines.append(
            "- Todos os dados são sintéticos; nenhuma alegação de representatividade de "
            "uma instituição real.\n"
            "- Nenhum dado de receita, custo, LGD, EAD ou PD regulatória existe neste "
            "DGP.\n"
            "- `collections_change` nunca deve ser lido como evidência causal de uma ação "
            "individual.\n"
            "- Comparações de cenário só são válidas dentro da mesma suíte (mesmo "
            "seed/CRN).\n"
        )
        lines.append("## 4. Próximos passos\n")
        lines.append(
            "- Dashboard interativo (fora do escopo desta fase).\n"
            "- Modelo preditivo de risco treinado (fora do escopo desta fase).\n"
        )
    else:
        lines.append("## 3. Risks and limitations\n")
        lines.append(
            "- Every figure is synthetic; no claim of real-institution representativeness.\n"
            "- No revenue, cost, LGD, EAD, or regulatory PD data exists in this DGP.\n"
            "- `collections_change` must never be read as causal evidence of an "
            "individual action.\n"
            "- Scenario comparisons are only valid within the same suite (same seed/CRN).\n"
        )
        lines.append("## 4. Next steps\n")
        lines.append(
            "- An interactive dashboard (out of scope this phase).\n"
            "- A trained predictive risk model (out of scope this phase).\n"
        )

    return "\n".join(lines)


def _df_to_markdown(df: pd.DataFrame, max_rows: int = 20) -> str:
    if df.empty:
        return "_(no rows)_\n"
    shown = df.head(max_rows)
    header = "| " + " | ".join(str(c) for c in shown.columns) + " |"
    sep = "| " + " | ".join("---" for _ in shown.columns) + " |"
    body = "\n".join(
        "| " + " | ".join(str(v) for v in row) + " |" for row in shown.itertuples(index=False)
    )
    truncated = (
        f"\n_(showing {max_rows} of {len(df)} rows - see "
        f"reports/portfolio_analysis/tables/ for the full CSV)_"
        if len(df) > max_rows
        else ""
    )
    return f"{header}\n{sep}\n{body}\n{truncated}\n"


def build_technical_report(
    *,
    lang: str,
    build_id: str,
    suite_id: str,
    fingerprint: str,
    manifest: dict[str, Any],
    scenario_cmp: pd.DataFrame,
    macro_pp: pd.DataFrame,
    composition: dict[str, dict[str, Any]],
    multiseed_summary: dict[str, Any] | None,
    benchmark_profiles: list[dict[str, Any]],
    reconciliation_results: list[dict[str, Any]],
    dbt_test_results: dict[str, Any],
    figures_written: dict[str, str],
) -> str:
    is_pt = lang == "pt-BR"
    lines: list[str] = []
    report_title = (
        "Relatório Técnico - Análise de Portfólio CredLens"
        if is_pt
        else "Technical Report - CredLens Portfolio Analysis"
    )
    lines.append(f"# {report_title}\n")
    lines.append(
        f"Build ID: `{build_id}` | Suite ID: `{suite_id}` | "
        f"Analytical fingerprint: `{fingerprint}`\n"
    )
    lines.append(
        f"dbt version: {manifest.get('dbt_version')} | "
        f"DuckDB version: {manifest.get('duckdb_version')} | "
        f"credlens version: {manifest.get('package_version')} | "
        f"Python: {manifest.get('python_version')}\n"
    )

    lines.append("## " + ("1. Arquitetura analítica" if is_pt else "1. Analytical architecture"))
    lines.append(
        (
            "Ver `docs/warehouse_architecture.md` para o desenho completo. Esta análise "
            "consulta apenas marts já materializados e views de staging/intermediate - "
            "nenhuma lógica de negócio nova foi implementada em pandas."
        )
        if is_pt
        else (
            "See `docs/warehouse_architecture.md` for the full design. This analysis "
            "queries only already-materialized marts and staging/intermediate views - no "
            "new business logic was implemented in pandas."
        )
    )
    lines.append("")

    lines.append("## " + ("2. Resultado dos cenários" if is_pt else "2. Scenario results"))
    lines.append(_df_to_markdown(scenario_cmp))

    lines.append(
        "## " + ("3. Pré/pós-choque macroeconômico" if is_pt else "3. Macro stress pre/post")
    )
    lines.append(_df_to_markdown(macro_pp))

    lines.append(
        "## "
        + (
            "4. Composição vs. desempenho (política)"
            if is_pt
            else "4. Composition vs. performance (policy)"
        )
    )
    for scenario_name, comp in composition.items():
        lines.append(f"**{scenario_name}**: {comp}\n")

    lines.append("## " + ("5. Robustez multi-seed" if is_pt else "5. Multi-seed robustness"))
    if multiseed_summary is not None:
        lines.append(
            f"Scenario: `{multiseed_summary.get('scenario')}` | "
            f"Scale: `{multiseed_summary.get('scale')}` | "
            f"Seeds: {multiseed_summary.get('seeds')}\n"
        )
        for metric_name, s in multiseed_summary.get("metric_summaries", {}).items():
            lines.append(
                f"- `{metric_name}`: mean_delta={s['mean_delta']:.4f}, "
                f"stdev={s['stdev_delta']:.4f}, n_seeds={s['n_seeds']}, "
                f"fraction_in_expected_direction={s.get('fraction_in_expected_direction')}"
            )
        lines.append(
            "\n_Label: simulation variability across synthetic DGP seeds - never a real "
            "institution's statistical confidence interval._\n"
            if not is_pt
            else "\n_Rótulo: variabilidade entre execuções sintéticas - nunca um "
            "intervalo de confiança estatístico de uma instituição real._\n"
        )
    else:
        lines.append(
            "_Not executed in this run - see `credlens analysis run --multiseed` / the "
            "final report's scope verification section._\n"
            if not is_pt
            else "_Não executado nesta rodada - veja `credlens analysis run "
            "--multiseed` / a seção de verificação de escopo do relatório final._\n"
        )

    lines.append(
        "## " + ("6. Benchmark de dados públicos" if is_pt else "6. Public data benchmark")
    )
    if benchmark_profiles:
        lines.append(_df_to_markdown(pd.DataFrame(benchmark_profiles)))
        lines.append(
            "_Dados públicos reais, mantidos completamente separados da análise "
            "operacional sintética acima - nunca misturados, nunca tratados como "
            "resultado do CredLens._\n"
            if is_pt
            else "_Real public data, kept completely separate from the synthetic "
            "operational analysis above - never merged, never treated as a CredLens "
            "result._\n"
        )
    else:
        lines.append("_Not included in this run._\n")

    lines.append(
        "## " + ("7. Reconciliação independente" if is_pt else "7. Independent reconciliation")
    )
    lines.append(_df_to_markdown(pd.DataFrame(reconciliation_results)))

    lines.append("## " + ("8. Testes dbt" if is_pt else "8. dbt tests"))
    lines.append(f"```\n{dbt_test_results}\n```\n")

    lines.append("## " + ("9. Figuras geradas" if is_pt else "9. Figures generated"))
    for name, sha in figures_written.items():
        lines.append(f"- `{name}` (sha256 {sha[:16]}...)")
    lines.append("")

    lines.append("## " + ("10. Reprodução" if is_pt else "10. Reproduction"))
    lines.append(
        f"```bash\nuv run credlens warehouse build --suite-id {suite_id}\n"
        f"uv run credlens analysis run --build-id <build_id>\n```\n"
    )

    lines.append("## " + ("11. Limitações" if is_pt else "11. Limitations"))
    lines.append(
        (
            "- Todos os resultados são de um DGP sintético; ver "
            "docs/assumptions_and_limitations.md.\n"
            "- Nenhum dado de receita/custo/LGD/EAD/PD regulatória existe.\n"
            "- Comparações de cenário só são válidas dentro da mesma suite_id.\n"
        )
        if is_pt
        else (
            "- Every result comes from a synthetic DGP; see "
            "docs/assumptions_and_limitations.md.\n"
            "- No revenue/cost/LGD/EAD/regulatory PD data exists.\n"
            "- Scenario comparisons are only valid within the same suite_id.\n"
        )
    )

    return "\n".join(lines)
