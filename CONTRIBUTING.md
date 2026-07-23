# Contributing to CredLens

Thanks for your interest. This is a portfolio project, currently in its foundation phase (see `docs/roadmap.md`), but it's built to the same standard a real contribution workflow would use.

## Ground rules

- Keep changes scoped to the phase currently in progress (see `docs/roadmap.md`). If you want to work on a future phase, open an issue to discuss scope first.
- Never commit real data, credentials, or personal information — see `SECURITY.md` and `.gitignore`.
- Don't fabricate results. If a validation didn't run, say so; if a number isn't computed, don't imply it is (see `docs/assumptions_and_limitations.md` for why this matters here specifically).

## Prerequisites

- Python 3.11 or newer.
- [`uv`](https://docs.astral.sh/uv/) (recommended) or a standard `venv` + `pip` as a fallback.
- Git.

## Setup

```bash
git clone <this-repository>
cd credlens-credit-analytics
uv sync --all-groups
```

Without `uv`:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Development workflow

| Task | Command |
|---|---|
| Run the CLI | `uv run credlens doctor` |
| Lint | `uv run ruff check .` |
| Auto-fix lint issues | `uv run ruff check --fix .` |
| Check formatting | `uv run ruff format --check .` |
| Apply formatting | `uv run ruff format .` |
| Type check | `uv run mypy src tests` |
| Run tests | `uv run pytest` |
| Run tests with coverage | `uv run pytest --cov=credlens --cov-report=term-missing` |

A `Makefile` wraps these (`make lint`, `make test`, etc.) for convenience; it is not required.

Before opening a pull request, run all of the above locally — the same checks run in CI (`.github/workflows/ci.yml`) and a failing check will block merge.

## Code style

- Python code, identifiers, and docstrings are in English, even though project documentation has a Portuguese counterpart (`README.pt-BR.md`).
- No abbreviations that aren't immediately obvious; prefer a clear full name over a clever short one.
- Formatting and import order are enforced by Ruff — don't hand-format against it.
- Type hints are required on new code; `mypy --strict` runs in CI.
- Avoid bare `except:` or broad `except Exception:` blocks that swallow errors silently. Catch specific exceptions and either handle them meaningfully or let them propagate.
- Don't add a dependency (runtime or dev) without a concrete reason tied to the current phase's scope.

## Tests

- New code should come with tests. Foundation-phase tests live in `tests/` and mirror `src/credlens/` by module.
- Prefer testing behavior (what a function returns or raises) over implementation detail.
- Don't disable or skip a test to make CI pass — fix the underlying issue, or discuss the test's validity in the PR description.

## Commit and PR conventions

- Keep commits focused; a commit message should explain *why*, not just *what* (the diff already shows what).
- Fill out the pull request template (`.github/pull_request_template.md`), including the scope-boundary checklist.
- If your change touches a phase boundary (e.g., introduces a data dependency ahead of the data acquisition phase), call that out explicitly in the PR description.

## Documentation

- Business/architecture docs live in `docs/`. If your change affects what a document claims is implemented vs. planned, update that document in the same PR — don't let docs drift from reality.
- KPI definitions in `docs/kpi_dictionary.md` carry a `status` field (`proposed` / `requires_validation`, evolving toward `implemented` in later phases). Update it if your change actually validates or implements a KPI; don't upgrade a status without the corresponding work.

## Questions

Open an issue using the templates in `.github/ISSUE_TEMPLATE/`.
