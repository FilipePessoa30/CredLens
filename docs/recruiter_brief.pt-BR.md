# Resumo para Recrutadores — CredLens

*Uma página. English version: [recruiter_brief.md](recruiter_brief.md). Detalhe completo: [../README.md](../README.md) / [../README.pt-BR.md](../README.pt-BR.md), [../PORTFOLIO.pt-BR.md](../PORTFOLIO.pt-BR.md).*

## O desafio

Construir um projeto de analytics de carteira de crédito + modelagem de risco que se comporte como um código de produção real — não um único notebook — sendo totalmente reproduzível em um laptop, sem dependência de dados externos, e honesto sobre o que um benchmark histórico e uma carteira sintética podem e não podem provar.

## O que foi de fato feito

- Desenho e documentação de um processo gerador de dados (DGP) para uma carteira sintética (com seed, reprodutível, com separação explícita entre verdade e observado), mais 64 modelos dbt sobre DuckDB (staging → marts), cada um reconciliado independentemente contra uma reimplementação em Python da mesma lógica de KPI.
- Construção de uma camada de análise de carteira (funil, inadimplência, safras, cura/cobrança, cenários contrafactuais) e um dashboard Streamlit de 10 páginas, cada página coberta por execução automatizada via `AppTest` e, nesta release, por uma passagem real com navegador headless.
- Treinamento de uma regressão logística interpretável de 18 features (modelo comportamental de alerta antecipado de inadimplência) sobre o benchmark UCI "Default of Credit Card Clients", com controles completos de vazamento, calibração, diagnósticos de subgrupo e 9 testes de robustez, além de um challenger HistGradientBoosting.
- Construção de um *segundo pacote de validação, independente*, que nunca confia nos próprios números reportados pelo modelo — ele recomputa cada métrica a partir de previsões congeladas e roda dois controles negativos por permutação separados (um teste clássico de permutação de rótulos e um teste de re-treino do pipeline completo).
- Construção de uma simulação de monitoramento (limiares de drift/desempenho calibrados a partir da própria distribuição de referência do modelo, uma hierarquia de escalonamento sinal → alerta → incidente, uma matriz de avaliação de detecção sobre 12 cenários de perturbação documentados).
- Este ciclo de release reauditou toda a stack em busca de lacunas metodológicas remanescentes, encontrou e corrigiu dois problemas reais e medidos (uma taxa de falso alerta de ~60% causada por um problema de comparações múltiplas não corrigido; um viés de otimismo de ~0,012 no ROC-AUC da referência de desempenho do monitoramento), e construiu uma variante de modelo remediada, registrada separadamente — nunca substituindo o modelo original.

## Stack

Python (pandas, scikit-learn, DuckDB, dbt-core), Streamlit + Plotly, pytest + mypy (estrito) + ruff, GitHub Actions CI (8 jobs paralelos), uv para gestão de dependências, Selenium para verificação do dashboard com navegador real.

## Decisões demonstradas

- Escolher um benchmark público histórico para a modelagem (auditabilidade, sem rótulos de inadimplência fabricados) em vez de fabricar rótulos "reais" de inadimplência para a carteira sintética.
- Escolher regressão logística como candidata interpretável principal, com um challenger não-linear para comparação, e não o contrário.
- Escolher divulgar um holdout repetidamente observado em vez de chamá-lo de "intocado" quando isso deixou de ser verdade.
- Escolher uma calibração estatística por família em vez de um limiar fixo genérico de mercado, depois que o limiar fixo se mostrou responsável por um excesso de falsos alertas.

## Impacto demonstrado (este é um projeto de portfólio — ver limitações)

Não é uma alegação de impacto financeiro real. O que é demonstrado: um pipeline completo e auditável de analytics até monitoramento; um erro metodológico real, encontrado e corrigido por meio de revalidação independente, nunca simplesmente assumido como inexistente; um projeto que pode ser reproduzido de ponta a ponta por um estranho a partir de um clone limpo do repositório.

## Limitações

Benchmark histórico, não-brasileiro; carteira sintética; nenhuma certificação de fairness; nenhuma alegação de conformidade legal; não é adequado para decisões reais de concessão de crédito. Ver [../docs/assumptions_and_limitations.md](assumptions_and_limitations.md).

## Para onde ir em seguida

[../PORTFOLIO.pt-BR.md](../PORTFOLIO.pt-BR.md) (resumo de 2 minutos) → [../README.md](../README.md) / [../README.pt-BR.md](../README.pt-BR.md) (referência técnica completa) → [interview_guide.pt-BR.md](interview_guide.pt-BR.md) (perguntas e respostas específicas).
