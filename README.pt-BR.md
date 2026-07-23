[Read in English](README.md)

# CredLens — Credit Risk & Portfolio Analytics

**O CredLens transforma a carteira de crédito de uma credor digital em um produto de analytics reprodutível e testado — da pergunta de negócio ao KPI, do KPI à decisão.**

**Status: fase de fundação.** Este repositório contém, por enquanto, apenas a definição do negócio, a arquitetura e o esqueleto do projeto. Nenhum dado foi adquirido, nenhum modelo foi treinado, nenhum dashboard existe e nenhuma métrica abaixo foi calculada. Todo número que você esperaria ver aqui (tamanho de carteira, inadimplência, ROI, acurácia) está deliberadamente ausente — veja [Capacidades atuais](#capacidades-atuais) e [`docs/roadmap.md`](docs/roadmap.md) para os próximos passos.

## O cenário de negócio

O CredLens é construído em torno de uma empresa fictícia de crédito digital que concede empréstimos pessoais sem garantia. Como qualquer credor, ela precisa equilibrar quatro alavancas ao mesmo tempo: **quantos proponentes aprovar, quanto risco carregar, quanto cobrar e quanto recuperar quando os pagamentos atrasam.** Otimizar uma alavanca isoladamente (por exemplo, aprovar mais pessoas) tende a prejudicar outra (por exemplo, a inadimplência). A liderança da empresa precisa de uma visão compartilhada e defensável da carteira para fazer essa troca de forma deliberada, não acidental.

A pergunta executiva central que organiza este projeto:

> **Como aumentar ou preservar a rentabilidade da carteira de crédito, equilibrando aprovação, inadimplência, perda esperada e recuperação?**

O contexto completo — situação, sintomas, perguntas executivas e a árvore de diagnóstico que os conecta — está em [`docs/business_problem.md`](docs/business_problem.md). Nada ali é apresentado como já respondido; veja a separação explícita entre descrição, diagnóstico, previsão e decisão nesse documento.

## Perguntas que este projeto pretende ajudar a responder no futuro

- A inadimplência está crescendo por causa de clientes novos, de safras específicas, ou de uma mudança no mix da carteira?
- Quais segmentos concentram maior exposição e perda?
- O aumento da aprovação está de fato gerando crescimento *rentável*, ou apenas mais volume?
- Quais safras estão deteriorando mais rápido, e a que velocidade?
- Como os clientes transitam entre "em dia" e as diferentes faixas de atraso ao longo do tempo?
- Qual é a efetividade das estratégias de cobrança em uso?
- Se o ponto de corte de aprovação mudasse, o que aconteceria com volume aprovado, risco e resultado esperado?
- O que a liderança deveria acompanhar diariamente, mensalmente e por safra?

Essas perguntas estão formalizadas e estruturadas agora (veja [`docs/business_problem.md`](docs/business_problem.md) e [`docs/kpi_dictionary.md`](docs/kpi_dictionary.md)); elas **não** são respondidas nesta fase.

## Produtos analíticos planejados

Quando as próximas fases forem implementadas, este projeto está escopado para produzir:

- Um **dicionário de KPIs e camada semântica** cobrindo originação, carteira, inadimplência, safras, recuperação e rentabilidade — cada um com fórmula, granularidade e responsável explícitos (rascunho: [`docs/kpi_dictionary.md`](docs/kpi_dictionary.md)).
- Um **warehouse modelado em SQL/dbt** (DuckDB para desenvolvimento local) com modelos dimensionais testados e documentados.
- **Análise de carteira e safras** — crescimento, mudança de mix, roll rates de inadimplência, cure rates — construída sobre esse warehouse.
- Um **modelo de risco de crédito interpretável** e um **simulador de política** para estimar o efeito de mudanças no ponto de corte antes que elas sejam feitas.
- Um **dashboard em Power BI** e uma aplicação demonstrativa leve para exploração por stakeholders.

Nada disso existe ainda. Está escopado, não implementado — veja [`docs/roadmap.md`](docs/roadmap.md).

## Arquitetura (resumo)

```mermaid
flowchart LR
    A[Dados publicos + sinteticos] --> B[Ingestao]
    B --> C[Checagens de qualidade]
    C --> D[Transformacao / modelos dbt]
    D --> E[Warehouse SQL - DuckDB]
    E --> F[Camada analitica - KPIs, safras, risco]
    F --> G[Apresentacao - Power BI, app demo]
```

Esta é a arquitetura-alvo do projeto completo, não o que está implementado hoje. As responsabilidades de cada camada, a justificativa das tecnologias e o que já existe versus o que está planejado estão documentados em [`docs/architecture.md`](docs/architecture.md).

## Capacidades atuais

O que existe no repositório agora:

- Esqueleto do projeto: layout de código-fonte, gestão de dependências, configuração de lint/tipagem/testes.
- Uma CLI mínima e testada (`credlens --help`, `credlens version`, `credlens doctor`) que verifica a *instalação*, não a lógica de negócio.
- Carregamento centralizado de configuração (`config/base.yaml`) com validação e mensagens de erro claras.
- Configuração de logging estruturado.
- Documentação de negócio: charter, definição do problema de negócio, mapa de stakeholders, dicionário de KPIs (apenas definições, sem valores calculados), estratégia de dados, arquitetura, premissas e limitações, glossário, roadmap.
- CI (GitHub Actions): lint, checagem de formatação, checagem de tipos, testes com cobertura — a cada push.

## Capacidades planejadas (ainda não implementadas)

- Aquisição de dados e auditoria de licenciamento das bases públicas candidatas.
- Uma camada operacional sintética reprodutível.
- Modelagem dimensional e transformações em dbt.
- Um warehouse SQL consultável (DuckDB, opcionalmente Postgres).
- Validação de qualidade de dados (Pandera ou equivalente).
- Análise de carteira, safras e roll rate.
- Um modelo interpretável de probabilidade de inadimplência e cálculo de perda esperada.
- Um simulador de ponto de corte / política de crédito.
- Um dashboard em Power BI e uma aplicação demonstrativa.
- Containerização e um pipeline de CI/CD ampliado.

Veja [`docs/roadmap.md`](docs/roadmap.md) para a sequência completa de fases e suas dependências.

## Início rápido

Requer Python 3.11+ e, idealmente, [`uv`](https://docs.astral.sh/uv/).

```bash
git clone <este-repositorio>
cd credlens-credit-analytics

# Instalar (o uv resolve e trava as dependências automaticamente)
uv sync --all-groups

# Verificar a instalação
uv run credlens --help
uv run credlens version
uv run credlens doctor
```

Sem `uv`, use um ambiente virtual padrão:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
credlens --help
```

> Nota: `pip install -e ".[dev]"` requer que `dev` esteja declarado como grupo opcional de dependências. Este projeto define suas dependências de desenvolvimento em `[dependency-groups]` (PEP 735) para uso com `uv`; se instalar com `pip` puro, instale os pacotes listados em `dependency-groups.dev` no `pyproject.toml` individualmente (`pip install pytest pytest-cov ruff mypy types-PyYAML`).

## Comandos de desenvolvimento

Um `Makefile` é fornecido por conveniência. Todo alvo tem um equivalente documentado via `uv run` para quem não usa `make`.

| Tarefa | Make | Direto (uv) |
|---|---|---|
| Instalar dependências | `make install` | `uv sync --all-groups` |
| Lint | `make lint` | `uv run ruff check .` |
| Checar formatação | `make format-check` | `uv run ruff format --check .` |
| Formatar (gravar) | `make format` | `uv run ruff format .` |
| Checar tipos | `make typecheck` | `uv run mypy src tests` |
| Testes | `make test` | `uv run pytest` |
| Testes + cobertura | `make coverage` | `uv run pytest --cov=credlens --cov-report=term-missing` |
| Rodar a CLI | `make run ARGS="doctor"` | `uv run credlens doctor` |
| Tudo que o CI executa | `make ci` | ver `.github/workflows/ci.yml` |

Veja [`CONTRIBUTING.md`](CONTRIBUTING.md) para o fluxo completo de contribuição.

## Testes

```bash
uv run pytest
```

Os testes desta fase cobrem: importação do pacote e exposição da versão, comandos `--help`/`version`/`doctor` da CLI, e carregamento de configuração (incluindo os caminhos de erro de arquivo ausente, YAML inválido e falha de validação de schema). A cobertura é medida sobre o código que existe nesta fase (`src/credlens`) — não é um proxy de quanto do produto final está pronto.

## Estrutura do repositório

```text
credlens-credit-analytics/
├── README.md / README.pt-BR.md   # Este arquivo e sua versão em português
├── pyproject.toml                # Metadados do pacote, dependências, configuração de ferramentas
├── config/                       # base.yaml - configuração estrutural (sem segredos)
├── data/                         # Vazio propositalmente nesta fase (ver data/README.md)
├── docs/                         # Documentação de negócio e arquitetura
├── src/credlens/                 # Pacote da aplicação (CLI, config, logging)
├── tests/                        # Suíte de testes Pytest
└── .github/                      # Workflow de CI e templates de issue/PR
```

## Estratégia de dados (resumo)

A estratégia-alvo é **dados públicos + uma camada operacional sintética reprodutível**: bases públicas de crédito/macroeconômicas reais e licenciadas fornecem estrutura e distribuições realistas; uma camada sintética documentada e gerada por código preenche o detalhe operacional (por exemplo, transições diárias de inadimplência) que bases públicas não expõem, sem nunca apresentar valores sintéticos como resultados reais observados. Fontes candidatas, status de licenciamento e a abordagem de rotulagem sintético/público estão registrados em [`docs/data_strategy.md`](docs/data_strategy.md). Nenhuma base foi baixada nesta fase.

## Limitações

Este é um projeto de portfólio sobre uma empresa **fictícia**. Não contém clientes reais, dados pessoais ou financeiros reais e, nesta fase, nenhum resultado de negócio calculado. Não pode ser usado para conceder crédito real, e qualquer modelo ou métrica futura que ele produza exigirá validação estatística, jurídica e regulatória independente antes de qualquer uso real. Veja [`docs/assumptions_and_limitations.md`](docs/assumptions_and_limitations.md) para a lista completa.

## Roadmap

Veja [`docs/roadmap.md`](docs/roadmap.md) para o plano faseado, desde esta fundação até aquisição de dados, modelagem, analytics, score de risco, simulação de política, dashboards e preparação para publicação.

## Licença

O código é licenciado sob [MIT](LICENSE). Qualquer base de dados de terceiros usada em fases futuras permanece sujeita à sua própria licença — veja [`docs/data_strategy.md`](docs/data_strategy.md).

---

[Read in English](README.md)
