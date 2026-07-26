# Estudo de Caso: Carteira de Crédito Sintética CredLens

**Todos os números abaixo descrevem um processo de geração de dados (DGP) totalmente sintético, não uma instituição financeira real.**

Build: `BUILD_kpi_test` | Suite: `SUITE_sample_2026` | Analytical fingerprint: `a891dff7f62b3ff4...`

## 1. Contexto

O CredLens é um projeto de portfólio que simula uma fintech de crédito digital brasileira. Esta análise usa a suíte de cenários contrafactuais (baseline, expansão de política, aperto de política, estresse macroeconômico, mudança de cobrança) construída sobre um warehouse DuckDB + dbt.

## 2. Principais resultados

> **Pergunta:** O que acontece com aprovações e risco se o cutoff de aprovação for relaxado (policy_expansion)?
>
> **Evidência:** approval_rate 57.43% -> 88.32% (delta 30.89%); write-offs 51 -> 82. Of the 2935 contracts booked in both runs, PAR90 was 5.61%; the 2384 marginal contracts expansion added had PAR90 6.84%.
>
> **Interpretação:** Dentro deste cenário sintético, relaxar o cutoff aumentou aprovações e adicionou uma população de contratos marginais com risco mensuravelmente maior que a população compartilhada - exatamente o mecanismo que uma relaxação de política real deveria acionar.
>
> **Decisão que poderia apoiar:** Poderia informar uma discussão sobre o trade-off volume/risco de uma mudança de cutoff - NÃO uma conclusão de rentabilidade (não existem dados de receita/custo neste DGP).
>
> **Risco/limitação:** Apenas DGP sintético; a mecânica do score de aprovação é simplificada frente a um modelo de underwriting real.

> **Pergunta:** Um choque macroeconômico afeta a carteira, e só depois que ele ocorre?
>
> **Evidência:** Pre-shock PAR90 delta (stress - baseline): 0.00% (should be ~0). Post-shock PAR90 delta: 5.59%.
>
> **Interpretação:** A garantia de identidade pré-choque do DGP se sustenta empiricamente neste build - baseline e estresse são indistinguíveis antes da data do choque, e divergem mensuravelmente depois.
>
> **Decisão que poderia apoiar:** Apoia tratar o efeito do choque como isolado ao período pós-choque ao raciocinar sobre este cenário.
>
> **Risco/limitação:** Uma suíte/seed; veja a seção multi-seed do relatório técnico para robustez entre seeds.

> **Pergunta:** Intensificar a atividade de cobrança muda os resultados, e isso pode ser atribuído a contatos individuais?
>
> **Evidência:** approval_rate delta: 0.00% (expected ~0, collections_change does not touch approval); write-off count delta: -34.
>
> **Interpretação:** collections_change varia apenas parâmetros AGREGADOS de cenário neste DGP - não há vínculo causal por contato registrado.
>
> **Decisão que poderia apoiar:** Não pode apoiar uma alegação sobre qual ação específica de cobrança causou qual resultado.
>
> **Risco/limitação:** Explicitamente NÃO é evidência causal para nenhuma estratégia de cobrança individual - veja limitações.

> **Pergunta:** Quanto foi baixado vs. recuperado entre cenários neste build?
>
> **Evidência:** Total write-off: R$ 1,462,751.07; total recovery: R$ 21,587.07 (1.48% recovery rate).
>
> **Interpretação:** A taxa de recuperação reflete a regra de probabilidade/valor de recuperação configurada no DGP, não o desempenho de uma operação de cobrança real.
>
> **Decisão que poderia apoiar:** Ilustra o formato de um dashboard de KPI de baixa/recuperação, não uma estimativa real de recuperação.
>
> **Risco/limitação:** Sem modelagem de LGD/EAD - recovery_rate aqui é um resultado de configuração do DGP.

## 3. Riscos e limitações

- Todos os dados são sintéticos; nenhuma alegação de representatividade de uma instituição real.
- Nenhum dado de receita, custo, LGD, EAD ou PD regulatória existe neste DGP.
- `collections_change` nunca deve ser lido como evidência causal de uma ação individual.
- Comparações de cenário só são válidas dentro da mesma suíte (mesmo seed/CRN).

## 4. Próximos passos

- Dashboard interativo (fora do escopo desta fase).
- Modelo preditivo de risco treinado (fora do escopo desta fase).
