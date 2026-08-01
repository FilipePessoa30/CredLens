# CredLens — Resumo de Portfólio

*Leitura de 2 minutos. Para o detalhe técnico completo, ver [README.md](README.md) (inglês, principal) e [README.pt-BR.md](README.pt-BR.md); para uma visão de uma página para recrutadores, ver [docs/recruiter_brief.pt-BR.md](docs/recruiter_brief.pt-BR.md); para respostas prontas para entrevista, ver [docs/interview_guide.pt-BR.md](docs/interview_guide.pt-BR.md). English version: [PORTFOLIO.md](PORTFOLIO.md).*

## O problema

A gestão de uma carteira de crédito envolve equipes de risco, crédito, cobrança, financeiro e produto, cada uma enxergando uma fatia da mesma carteira através de ferramentas e definições diferentes — o que produz divergência de métricas e respostas lentas e artesanais para perguntas como "qual safra está piorando?". O CredLens é um projeto de portfólio (não uma empresa real nem dados reais) construído para demonstrar como uma única stack de analytics + modelagem + monitoramento, versionada e testada, resolve esse problema de ponta a ponta.

## Stakeholders

Liderança executiva, gestão de risco, crédito/underwriting, cobrança, financeiro, produto, operações, dados & tecnologia, e auditoria/governança — ver `docs/stakeholder_map.md`. Cada um tem uma decisão distinta que o produto foi desenhado para eventualmente apoiar (cutoffs de aprovação, priorização de cobrança, trade-offs entre crescimento e perda).

## Dados

Duas fontes de dados, usadas para dois propósitos diferentes e explicitamente rotulados, nunca misturadas:
- **Uma carteira sintética gerada** (`credlens.generation`) — eventos do ciclo de vida da originação até a cobrança para uma credora fictícia, construída a partir de um processo gerador de dados (DGP) documentado, com seed e reprodutível. Alimenta as páginas Executive Overview, Credit Funnel, Portfolio & Delinquency, Vintages, Cure/Collections e Scenario Lab do dashboard.
- **O benchmark público UCI "Default of Credit Card Clients"** (real, histórico, Taiwan, 2005, com licença pública) — alimenta o modelo comportamental de alerta antecipado, sua validação independente e a simulação de monitoramento. Nunca é misturado com os números da carteira sintética.

## Arquitetura

```
DGP sintético ───┐                   Benchmark UCI ──┐
                  ├─► DuckDB (dbt) ──► Análise ───┐   ├─► Modelagem ──► Validação   ──► Monitoramento
                  │   (staging→marts) (Python)    │   │   (sklearn)     independente     (drift,
                  │                               ▼   │                 (recomputação,    alertas,
                  └──────────────────────► Dashboard Streamlit (10 páginas) ◄┘             incidentes)
```

- **Modelagem SQL**: 64 modelos dbt (raw → staging → intermediário → dimensões → fatos → marts), 135+ testes dbt genéricos e singulares, rodando em DuckDB.
- **Reconciliação independente**: todo KPI calculado pelo dbt/SQL é re-derivado por uma implementação Python independente e comparado dentro de uma tolerância documentada — nunca "confie na query", sempre "prove a query".
- **Modelagem**: uma regressão logística interpretável de 18 features (modelo comportamental de alerta antecipado de inadimplência) mais um challenger HistGradientBoosting, com controles completos de vazamento, calibração, diagnósticos de subgrupo e testes de robustez.
- **Validação independente do modelo**: um pacote *separado* (`credlens.model_validation`) que nunca copia os números já reportados pelo modelo — ele recomputa discriminação/calibração a partir de previsões congeladas e roda dois testes de controle negativo por permutação independentes.
- **Simulação de monitoramento**: um fluxo simulado de scoring em lote sobre o próprio conjunto de teste bloqueado do modelo, com limiares calibrados de drift/desempenho e uma hierarquia de escalonamento sinal → alerta → incidente.
- **Dashboard**: 10 páginas Streamlit, cada uma coberta independentemente por AppTest e, nesta release, verificada com um navegador headless real (capturas de tela, checagem de erros de console).

## Resultados-chave, reais e medidos

- 1.599 testes automatizados, 94% de cobertura de statements, `mypy` estrito, lint + format `ruff` limpos, tudo em CI.
- Modelo comportamental: ROC-AUC 0,745 / PR-AUC 0,502 em um holdout de teste congelado, nunca re-treinado; revalidado independentemente com dois controles de permutação (999 + 100 reamostragens) em α=0,01.
- **Uma correção metodológica genuína, não uma repetição**: a auditoria desta release sobre o teste de permutação original encontrou e corrigiu um problema real de comparações múltiplas no monitoramento (um limiar ingênuo por feature produzia uma taxa de falso alerta de ~60% em 100 lotes genuinamente normais; um limiar calibrado por família trouxe isso para ~4%/1%), e um viés real de otimismo na referência de desempenho (treino+validação superestimava o ROC-AUC real do holdout em ~0,012).
- Uma regressão logística remediada, com 11 features, foi construída e registrada independentemente (`remediation_candidate`) após a descoberta de uma segunda colinearidade, antes mascarada — corroborada de duas formas diferentes — mantendo o modelo original intocado.
- A validação visual com navegador headless real nas 10 páginas do dashboard encontrou e corrigiu uma regressão real antes desta publicação (um bug de seleção padrão que mostraria a um visitante novo uma visão geral do Model Lab com todos os valores zerados).

## Limitações (declaradas com clareza)

Benchmark histórico, não-brasileiro; carteira sintética para as camadas de analytics; nenhuma certificação de fairness; nenhuma alegação de dinheiro real; o holdout de modelagem foi observado repetidamente (embora nunca re-ajustado) ao longo das fases — divulgado, não escondido. Lista completa: `docs/assumptions_and_limitations.md` e o campo `known_limitations` do manifesto de release.

## Como reproduzir

```bash
uv sync --all-groups --extra warehouse --extra analysis --extra dashboard --extra notebook --extra modeling
uv run pytest -m "not slow"          # suíte rápida
uv run credlens dashboard run --demo # explore as 10 páginas, sem precisar de build
```

Quick start completo, referência de CLI e todos os relatórios citados acima: [README.md](README.md) / [README.pt-BR.md](README.pt-BR.md).
