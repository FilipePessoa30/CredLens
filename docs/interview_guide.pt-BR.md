# Guia de Entrevista — CredLens

*Respostas rastreáveis para as perguntas mais prováveis sobre este projeto em uma entrevista. English version: [interview_guide.md](interview_guide.md). Nunca inventa experiência bancária profissional real — cada resposta abaixo está limitada ao que o próprio projeto demonstra.*

## "Por que dados sintéticos para as camadas de carteira?"

Porque não existe um dataset público, com granularidade de evento, realista, de carteira de crédito (originações, ciclos de faturamento, inadimplência, cobrança, cura) que seja ao mesmo tempo livre para redistribuir e rico o suficiente para construir uma análise de funil/safra/cobrança. Um processo gerador de dados documentado, com seed e reprodutível (`credlens.generation`, ver `docs/synthetic_generation_spec.md`) torna as camadas de analytics demonstráveis sem dados de uma instituição real — ao custo de nunca poder alegar que os números refletem comportamento do mundo real. Essa troca é declarada explicitamente em todo lugar onde os números da carteira sintética aparecem ("Synthetic data - illustrative portfolio").

## "Por que o benchmark UCI para o modelo, em vez da carteira sintética?"

Porque um rótulo de inadimplência sintético seria circular: o gerador teria que codificar *alguma* regra de inadimplência, e um modelo treinado para prever essa regra só provaria que consegue recuperar uma regra escrita pelo próprio criador. O dataset UCI "Default of Credit Card Clients" (Taiwan, 2005) é real, histórico, e tem um resultado de inadimplência real que ninguém fabricou — então um modelo treinado nele é ao menos avaliado contra comportamento genuíno, ainda que esse comportamento seja de um país, época e população diferentes de qualquer credora brasileira hipotética. Ver `docs/dataset_selection.md` e `docs/target_and_leakage_audit.md`.

## "Por que regressão logística como modelo principal, e não HistGradientBoosting?"

Porque o entregável principal é um modelo comportamental de alerta antecipado *interpretável*, com reason codes voltados ao executivo, e os coeficientes de um modelo linear se decompõem de forma aditiva e exata em uma contribuição por feature — sem necessidade de aproximação. O HistGradientBoosting é deliberadamente mantido como **challenger**, nunca promovido: comparado via Pareto contra a candidata logística em discriminação, calibração, estabilidade, robustez, tamanho e latência (`credlens model compare-candidates`), mostrando consistentemente maior discriminação bruta (ROC-AUC 0,780 vs 0,745) ao custo de interpretabilidade. Os dois fatos são reportados lado a lado — o projeto nunca esconde que o modelo linear não é a opção com melhor discriminação, apenas que era a opção certa para o requisito de interpretabilidade declarado.

## "Como o vazamento (leakage) foi evitado?"

Uma lista de permissão estática de features (`config/modeling/feature_registry.yml`) é o *único* caminho pelo qual uma coluna pode chegar ao treino — nada chega ao estimador que não esteja nela, e colunas demográficas (SEXO/EDUCAÇÃO/ESTADO CIVIL/IDADE) nunca estão nela (apenas auditoria pós-hoc). Cinco controles negativos funcionais rodam toda vez que um modelo é treinado: um controle de alvo embaralhado, um detector de discriminação quase perfeita, um controle apenas-com-IDs, e a rejeição direta da coluna-alvo ou de uma cópia exata dela como feature. Ver `docs/target_and_leakage_audit.md` e `credlens.modeling.leakage`.

## "Como os KPIs foram definidos?"

Todo KPI tem uma fórmula, granularidade e responsável explícitos em `docs/kpi_dictionary.md`/`config/kpi_catalog.yml` *antes* de qualquer SQL ser escrito contra ele — os marts do dbt implementam o catálogo, não o contrário. Cada KPI calculado em SQL é re-derivado independentemente em Python e reconciliado dentro de uma tolerância documentada (`credlens warehouse reconcile`), de forma que "o número do dashboard" e "o número do SQL" nunca são dois palpites não verificados.

## "Como o modelo foi validado?"

Duas vezes, por dois pacotes diferentes. `credlens.modeling` calcula a suíte original de discriminação/calibração/subgrupo/robustez no momento do treino. `credlens.model_validation` — um pacote *separado* — re-deriva cada um desses números a partir de evidência CONGELADA, nunca copiando o relatório original, e adicionalmente roda dois controles negativos independentes por permutação: um teste clássico de permutação de rótulos sobre previsões congeladas (999 reamostragens) e um teste de re-treino do pipeline completo com o alvo de treino embaralhado (100 reamostragens), ambos com α=0,01. A decisão de 14 gates é `validation_passed_with_limitations` — ver `reports/model_validation/validation_report.pt-BR.md`.

## "Por que o monitoramento produziu falsos alertas, e como foi recalibrado?"

O limiar original de drift por feature estava corretamente calibrado para UMA feature isolada (um corte no percentil 95), mas era então aplicado a 18 features independentemente a cada lote — um problema clássico de comparações múltiplas. Uma auditoria empírica desta release mediu a consequência real: ~60% dos lotes genuinamente normais (sem nenhum drift injetado) disparavam pelo menos um alerta. A correção foi um segundo limiar, calibrado por família (calibrado sobre o PSI MÁXIMO entre as 18 features por reamostragem, não o nulo marginal de uma única feature), o que reduziu a mesma medição para ~4%/1% (revisão/desvio material) — documentado em `config/monitoring/thresholds.yml` e `credlens.monitoring.calibration_study`.

## "O que mudaria com dados institucionais reais?"

O alvo precisaria de um resultado de inadimplência real e legalmente definido (não o rótulo de um benchmark); o conjunto de features precisaria de variáveis de underwriting/comportamentais validadas contra a experiência real de baixa contábil (charge-off); a análise de fairness de subgrupo precisaria ser uma revisão de conformidade, não um diagnóstico; a referência de monitoramento precisaria de um fluxo real de scoring em produção em vez de um conjunto de teste histórico particionado; e cada aviso "não é adequado para decisões reais de crédito" neste projeto precisaria ser substituído por um processo real de governança de risco de modelo com aprovação formal — exatamente o tipo de processo que a estrutura deste projeto (validação independente, gates documentados, monitoramento, decisões versionadas) usa como modelo, sem alegar SER um.

## "Qual parte demonstra SQL?"

`warehouse/` — 64 modelos dbt (raw → staging → intermediário → dimensões → fatos → marts) sobre DuckDB, 135+ testes genéricos/singulares, funções de janela para análise de safra/coorte, e a reconciliação independente em Python que prova que o SQL está certo em vez de apenas afirmar isso. Ver `docs/warehouse_architecture.md`.

## "Qual parte demonstra engenharia de software, não só análise?"

A CLI (`credlens ...`, dezenas de subcomandos, cada um testável independentemente), a estrutura em camadas dos pacotes (`generation` → `warehouse` → `analysis` → `dashboard` e, separadamente, `modeling` → `model_validation` → `monitoring`, cada um dependendo apenas do que está abaixo, nunca lateralmente ou acima), `mypy` estrito, lint+format `ruff`, 1.599 testes com 94% de cobertura, e um workflow de CI dividido em 8 jobs paralelos sem falhas mascaradas (`tests/test_ci_workflow_integrity.py` falha a build se um padrão do tipo `|| true` reaparecer).

## "Qual parte demonstra comunicação executiva?"

Os model cards, relatórios técnicos e relatórios de validação/monitoramento bilíngues (inglês/português) — cada um escrito para um leitor específico (um resumo executivo declara a decisão e a limitação já no primeiro parágrafo, nunca as esconde), e o enquadramento "Illustrative review-capacity scenario" do dashboard em toda simulação de ponto de operação, que declara claramente que nenhum limiar mostrado é otimizado por lucro ou é uma política recomendada.

## "Quais decisões este projeto NÃO consegue tomar por um negócio real?"

Se deve aprovar um solicitante específico (não existe aqui um score de originação); onde fixar um cutoff ótimo de lucro (os limiares são apenas cenários ilustrativos de capacidade); se o modelo é justo (fair) sob o padrão legal de uma jurisdição específica (os diagnósticos de subgrupo não são uma certificação de fairness); como a carteira se comportaria de fato sob um choque macroeconômico real (os cenários sintéticos são contrafactuais, não previsões). Cada um desses limites está declarado no model card e nos próprios rótulos de proveniência do dashboard, nunca deixado implícito.
