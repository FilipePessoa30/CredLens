# Model Card - Modelo Comportamental de Alerta Antecipado (Phase 8)

**Status**: candidate

## Nome e versão
- Experimento: `TEST_cli_pipeline`
- Modelo: `TEST_cli_model`
- Registro de features: v1.0.0

## Finalidade
Modelo comportamental de alerta antecipado para inadimplência no mês seguinte

## Uso pretendido
Diagnóstico técnico/estudo de caso de um modelo comportamental de alerta antecipado de
inadimplência, sobre um benchmark público histórico (UCI, Taiwan, 2005), demonstrando
rigor metodológico (leakage, calibração, incerteza, auditoria de subgrupo, robustez).

## Usos proibidos
- Decisão de concessão de crédito (origination) - o dataset não suporta essa framing.
- Aprovação/recusa automática, pricing, limite de crédito.
- PD regulatória, LGD, EAD, otimização por lucro.
- Qualquer alegação de conformidade legal/fair-lending.
- **Não é adequado para decisões reais de concessão de crédito.**

## Dataset
- Fonte: `uci-default-credit` (hash `45bcf4df62ff2e23...`)
- População: clientes de cartão de crédito, Taiwan, 2005 (não é população brasileira).
- Prevalência observada: 0.221167

## Target
Coluna `Y` - inadimplência no mês seguinte à janela de 6 meses.

## Split
Hash combinado do split: `4022f9cc24a66c25...` (seed=42, 60/20/20 estratificado).

## Features
18 features comportamentais engenheiradas (ver
`config/modeling/feature_registry.yml`) - nenhum atributo demográfico usado no treino.

## Atributos excluídos
SEXO, EDUCAÇÃO, ESTADO CIVIL, IDADE - apenas auditoria pós-hoc
(`credlens.modeling.subgroup_audit`).

## Modelos e seleção
logistic_regression (main) / hist_gradient_boosting (challenger). Comparação completa em `reports/modeling/tables/TEST_cli_pipeline__champion_challenger.csv`.

## Métricas (teste, bloqueado)
- ROC-AUC: 0.745123
- PR-AUC: 0.501927
- KS: 0.386644
- Brier: 0.142587
- Calibration slope/intercept: 0.947505 / -0.045965

## Calibração
Método selecionado: `none`. No calibration method produced a consistent improvement over the uncalibrated model on validation (best Brier 0.141257 vs. uncalibrated 0.141384) - the uncalibrated model is preserved.

## Thresholds
Illustrative review-capacity scenario (never profit-optimized)

## Incerteza
Ver `reports/modeling/tables/TEST_cli_pipeline__bootstrap.json` (bootstrap estratificado) e
`TEST_cli_pipeline__split_stability.csv` (múltiplas seeds de split).

## Auditoria de subgrupo
Ver seção "Fairness and subgroup diagnostics - not a compliance assessment" em
`reports/modeling/tables/TEST_cli_pipeline__subgroup_audit.csv`. Não é certificação de
fairness nem avaliação de conformidade legal.

## Interpretabilidade
Coeficientes/odds ratios, permutation importance, partial dependence e reason codes
descritivos - ver `reports/modeling/tables/TEST_cli_pipeline__coefficients.csv`,
`TEST_cli_pipeline__permutation_importance.csv`, `TEST_cli_pipeline__local_explanations.json`.

## Robustez
Ver `reports/modeling/tables/TEST_cli_pipeline__robustness.csv` - testes técnicos de
perturbação, não previsão de crise real.

## Limitações
- Historical public benchmark (UCI, Taiwan, 2005) - not a Brazilian population.
- Behavioral early-warning model for an existing account - not an origination score.
- Not suitable for real lending decisions.

## Riscos
Dataset histórico, de outro país/época; risco de generalização indevida para o
portfólio sintético do CredLens ou para qualquer instituição real.

## Governança
Este modelo foi treinado em um benchmark público histórico e não está conectado ao portfólio sintético do CredLens.

## Reprodução
`uv run credlens model train/evaluate/explain/audit-groups/stress-test/register/report`
com o mesmo `--experiment-id` e seed.

## Manutenção futura
Nenhuma promoção automática a "champion"/"production". Reavaliação obrigatória se o
registro de features, o contrato de target ou a fonte mudarem de versão.

**Não é adequado para decisões reais de concessão de crédito.**
