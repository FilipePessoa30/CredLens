# Relatório Técnico - Análise de Portfólio CredLens

Build ID: `BUILD_kpi_test` | Suite ID: `SUITE_sample_2026` | Analytical fingerprint: `a891dff7f62b3ff48eba09fbde07acffd075c18273d8cc4ca0fc73f05a8911cd`

dbt version: =1.12.0 | DuckDB version: 1.5.5 | credlens version: 0.6.0 | Python: 3.11.9

## 1. Arquitetura analítica
Ver `docs/warehouse_architecture.md` para o desenho completo. Esta análise consulta apenas marts já materializados e views de staging/intermediate - nenhuma lógica de negócio nova foi implementada em pandas.

## 2. Resultado dos cenários
| suite_id | scenario | run_id | approval_rate | baseline_approval_rate | approval_rate_delta_abs | approval_rate_delta_rel | dpd90_rate_final_month | baseline_dpd90_rate | dpd90_rate_delta_abs | write_off_count | baseline_write_off_count | write_off_count_delta_abs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SUITE_sample_2026 | collections_change | RUN_collections_change_sample_2026_7932bc75 | 0.5743034055727554 | 0.5743034055727554 | 0.0 | 0.0 | 0.025811209439528023 | 0.06478034251675353 | -0.03896913307722551 | 17 | 51 | -34 |
| SUITE_sample_2026 | macroeconomic_stress | RUN_macroeconomic_stress_sample_2026_c0afa13a | 0.5743034055727554 | 0.5743034055727554 | 0.0 | 0.0 | 0.19481429572529782 | 0.06478034251675353 | 0.13003395320854427 | 143 | 51 | 92 |
| SUITE_sample_2026 | policy_expansion | RUN_policy_expansion_sample_2026_275cb395 | 0.8831972980579792 | 0.5743034055727554 | 0.3088938924852238 | 0.5378583680470475 | 0.07380952380952381 | 0.06478034251675353 | 0.009029181292770277 | 82 | 51 | 31 |
| SUITE_sample_2026 | policy_tightening | RUN_policy_tightening_sample_2026_4aaa4164 | 0.21840698001688713 | 0.5743034055727554 | -0.35589642555586826 | -0.6197010536633178 | 0.05242718446601942 | 0.06478034251675353 | -0.012353158050734114 | 22 | 51 | -29 |


## 3. Pré/pós-choque macroeconômico
| suite_id | period | shock_date | baseline_n_months | stress_n_months | baseline_par90 | stress_par90 | par90_delta_abs | baseline_dpd90_rate | stress_dpd90_rate | dpd90_rate_delta_abs | baseline_outstanding_balance | stress_outstanding_balance | baseline_write_off_count | stress_write_off_count | write_off_count_delta_abs | baseline_write_off_amount | stress_write_off_amount |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SUITE_sample_2026 | post_shock | 2024-07-01 | 6 | 6 | 0.045599572794688605 | 0.10151179361604368 | 0.05591222082135507 | 0.05120592035286648 | 0.11517842021646123 | 0.06397249986359474 | 3749767.453333333 | 4185944.6466666665 | 51 | 143 | 92 | 237562.61 | 661433.05 |
| SUITE_sample_2026 | pre_shock | 2024-07-01 | 6 | 6 | 0.002084840992242281 | 0.002084840992242281 | 0.0 | 0.00235314191757023 | 0.00235314191757023 | 0.0 | 797065.7383333333 | 797065.7383333333 | 0 | 0 | 0 | 0.00 | 0.00 |


## 4. Composição vs. desempenho (política)
**policy_expansion**: {'suite_id': 'SUITE_sample_2026', 'scenario': 'policy_expansion', 'baseline_run_id': 'RUN_baseline_sample_2026_29e3fb70', 'scenario_run_id': 'RUN_policy_expansion_sample_2026_275cb395', 'shared_booked_count': 2935, 'baseline_only_count': 543, 'scenario_only_count': 2384, 'shared_par90': 0.056061631197636026, 'marginal_par90': 0.0683659897195828, 'shared_outstanding_balance': 4656761.04, 'marginal_outstanding_balance': 4067951.64, 'low_sample': False}

**policy_tightening**: {'suite_id': 'SUITE_sample_2026', 'scenario': 'policy_tightening', 'baseline_run_id': 'RUN_baseline_sample_2026_29e3fb70', 'scenario_run_id': 'RUN_policy_tightening_sample_2026_4aaa4164', 'shared_booked_count': 1119, 'baseline_only_count': 2359, 'scenario_only_count': 200, 'shared_par90': 0.03136479828757316, 'marginal_par90': 0.11929781694834575, 'shared_outstanding_balance': 1846287.34, 'marginal_outstanding_balance': 343865.89, 'low_sample': False}

## 5. Robustez multi-seed
Scenario: `macroeconomic_stress` | Scale: `smoke` | Seeds: [970001, 970002, 970003, 970004, 970005]

- `approval_rate`: mean_delta=0.0000, stdev=0.0000, n_seeds=5, fraction_in_expected_direction=None
- `booking_rate`: mean_delta=0.0000, stdev=0.0000, n_seeds=5, fraction_in_expected_direction=None
- `dpd30_plus_rate`: mean_delta=0.1566, stdev=0.0196, n_seeds=5, fraction_in_expected_direction=None
- `dpd60_plus_rate`: mean_delta=0.1075, stdev=0.0100, n_seeds=5, fraction_in_expected_direction=None
- `dpd90_plus_rate`: mean_delta=0.0672, stdev=0.0062, n_seeds=5, fraction_in_expected_direction=1.0
- `cure_rate`: mean_delta=-0.0490, stdev=0.0503, n_seeds=5, fraction_in_expected_direction=None
- `write_off_rate`: mean_delta=0.0333, stdev=0.0058, n_seeds=5, fraction_in_expected_direction=None

_Rótulo: variabilidade entre execuções sintéticas - nunca um intervalo de confiança estatístico de uma instituição real._

## 6. Benchmark de dados públicos
| source_id | num_rows | num_columns | missing_value_findings | domain_findings | context |
| --- | --- | --- | --- | --- | --- |
| bcb-sgs-20570 | 137 | 2 | 0 | 0 | {'population': 'Brazil, aggregate banking system', 'period': '2015-present (monthly)', 'target': 'n/a - a macro time series, not a labeled credit dataset', 'license': 'ODbL'} |
| bcb-sgs-21112 | 137 | 2 | 0 | 0 | {'population': 'Brazil, aggregate banking system', 'period': '2015-present (monthly)', 'target': 'n/a - a macro time series, not a labeled credit dataset', 'license': 'ODbL'} |
| south-german-credit | 1000 | 21 | 0 | 0 | {'population': 'Credit applicants, Germany', 'period': '1973-1975 (correction/republication donated 2019)', 'target': 'kredit (credit risk, binary)', 'license': 'CC BY 4.0'} |
| uci-default-credit | 30000 | 25 | 0 | 0 | {'population': 'Credit card clients, Taiwan', 'period': '2005', 'target': 'default payment next month (binary)', 'license': 'CC BY 4.0'} |


_Dados públicos reais, mantidos completamente separados da análise operacional sintética acima - nunca misturados, nunca tratados como resultado do CredLens._

## 7. Reconciliação independente
| name | run_id | python_value | sql_value | unit | tolerance | passed | detail |
| --- | --- | --- | --- | --- | --- | --- | --- |
| approval_rate | RUN_baseline_sample_2026_29e3fb70 | 0.5743034055727554 | 0.5743034055727554 | ratio | 1e-06 | True | python=0.5743034055727554 sql=0.5743034055727554 diff=0.0 tolerance=1e-06 |
| outstanding_balance | RUN_baseline_sample_2026_29e3fb70 | 5556650.17 | 5556650.17 | cents | 0.0 | True | python=555665017c sql=555665017c diff=0c (python=R$5556650.17 sql=R$5556650.17) |
| par90 | RUN_baseline_sample_2026_29e3fb70 | 0.05022040464354084 | 0.050220404643540835 | ratio | 1e-06 | True | python=0.05022040464354084 sql=0.050220404643540835 diff=6.938893903907228e-18 tolerance=1e-06 |
| cure_rate | RUN_baseline_sample_2026_29e3fb70 | 0.20899854862119013 | 0.20899854862119013 | ratio | 1e-06 | True | python=0.20899854862119013 sql=0.20899854862119013 diff=0.0 tolerance=1e-06 |
| write_off_amount | RUN_baseline_sample_2026_29e3fb70 | 237562.61 | 237562.61 | cents | 0.0 | True | python=23756261c sql=23756261c diff=0c (python=R$237562.61 sql=R$237562.61) |
| recovery_amount | RUN_baseline_sample_2026_29e3fb70 | 3027.89 | 3027.89 | cents | 0.0 | True | python=302789c sql=302789c diff=0c (python=R$3027.89 sql=R$3027.89) |
| paid_amount | RUN_baseline_sample_2026_29e3fb70 | 1557778.59 | 1557778.59 | cents | 0.0 | True | python=155777859c sql=155777859c diff=0c (python=R$1557778.59 sql=R$1557778.59) |
| scheduled_amount | RUN_baseline_sample_2026_29e3fb70 | 18361370.89 | 18361370.89 | cents | 0.0 | True | python=1836137089c sql=1836137089c diff=0c (python=R$18361370.89 sql=R$18361370.89) |
| approval_rate | RUN_collections_change_sample_2026_7932bc75 | 0.5743034055727554 | 0.5743034055727554 | ratio | 1e-06 | True | python=0.5743034055727554 sql=0.5743034055727554 diff=0.0 tolerance=1e-06 |
| outstanding_balance | RUN_collections_change_sample_2026_7932bc75 | 5509094.99 | 5509094.99 | cents | 0.0 | True | python=550909499c sql=550909499c diff=0c (python=R$5509094.99 sql=R$5509094.99) |
| par90 | RUN_collections_change_sample_2026_7932bc75 | 0.02500606546992939 | 0.02500606546992939 | ratio | 1e-06 | True | python=0.02500606546992939 sql=0.02500606546992939 diff=0.0 tolerance=1e-06 |
| cure_rate | RUN_collections_change_sample_2026_7932bc75 | 0.3684640522875817 | 0.3684640522875817 | ratio | 1e-06 | True | python=0.3684640522875817 sql=0.3684640522875817 diff=0.0 tolerance=1e-06 |
| write_off_amount | RUN_collections_change_sample_2026_7932bc75 | 87430.67 | 87430.67 | cents | 0.0 | True | python=8743067c sql=8743067c diff=0c (python=R$87430.67 sql=R$87430.67) |
| recovery_amount | RUN_collections_change_sample_2026_7932bc75 | 9105.76 | 9105.76 | cents | 0.0 | True | python=910576c sql=910576c diff=0c (python=R$9105.76 sql=R$9105.76) |
| paid_amount | RUN_collections_change_sample_2026_7932bc75 | 1746006.2 | 1746006.2 | cents | 0.0 | True | python=174600620c sql=174600620c diff=0c (python=R$1746006.20 sql=R$1746006.20) |
| scheduled_amount | RUN_collections_change_sample_2026_7932bc75 | 18361370.89 | 18361370.89 | cents | 0.0 | True | python=1836137089c sql=1836137089c diff=0c (python=R$18361370.89 sql=R$18361370.89) |
| approval_rate | RUN_macroeconomic_stress_sample_2026_c0afa13a | 0.5743034055727554 | 0.5743034055727554 | ratio | 1e-06 | True | python=0.5743034055727554 sql=0.5743034055727554 diff=0.0 tolerance=1e-06 |
| outstanding_balance | RUN_macroeconomic_stress_sample_2026_c0afa13a | 6240932.47 | 6240932.47 | cents | 0.0 | True | python=624093247c sql=624093247c diff=0c (python=R$6240932.47 sql=R$6240932.47) |
| par90 | RUN_macroeconomic_stress_sample_2026_c0afa13a | 0.1519973825321651 | 0.1519973825321651 | ratio | 1e-06 | True | python=0.1519973825321651 sql=0.1519973825321651 diff=0.0 tolerance=1e-06 |
| cure_rate | RUN_macroeconomic_stress_sample_2026_c0afa13a | 0.09562729873314263 | 0.09562729873314263 | ratio | 1e-06 | True | python=0.09562729873314263 sql=0.09562729873314263 diff=0.0 tolerance=1e-06 |

_(showing 20 of 40 rows - see reports/portfolio_analysis/tables/ for the full CSV)_

## 8. Testes dbt
```
{'passed': 135, 'failed': 0, 'errored': 0, 'skipped': 0, 'failures': []}
```

## 9. Figuras geradas
- `credit_funnel` (sha256 fcc1d9e8efeeb320...)
- `outstanding_balance_over_time` (sha256 a9a84ba01c752641...)
- `par_curves` (sha256 a4ac8541d94e30bc...)
- `roll_rate_heatmap` (sha256 7a7cdef6a1796f78...)
- `vintage_curves` (sha256 fbc5bff3e0ed49d8...)
- `cure_and_relapse` (sha256 19052170f0fcdd3a...)
- `writeoff_and_recovery` (sha256 fd11a5d61383c0b0...)
- `policy_scenario_comparison` (sha256 026e171244903fa5...)
- `macro_stress_pre_post` (sha256 e45b3dbc406dabda...)
- `multiseed_stability` (sha256 717ff8ad7c4e7c59...)
- `public_benchmark_overview` (sha256 fef9557678584bce...)
- `quality_provenance_scorecard` (sha256 57069f618acde3e0...)

## 10. Reprodução
```bash
uv run credlens warehouse build --suite-id SUITE_sample_2026
uv run credlens analysis run --build-id <build_id>
```

## 11. Limitações
- Todos os resultados são de um DGP sintético; ver docs/assumptions_and_limitations.md.
- Nenhum dado de receita/custo/LGD/EAD/PD regulatória existe.
- Comparações de cenário só são válidas dentro da mesma suite_id.
