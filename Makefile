.PHONY: install lint format format-check typecheck test coverage run doctor ci clean

# Convenience wrapper around `uv run ...`. Every target has a documented
# direct equivalent in README.md / CONTRIBUTING.md for contributors who
# don't have `make` available (e.g., on plain Windows without WSL/Git Bash).

install:
	uv sync --all-groups

lint:
	uv run ruff check .

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

typecheck:
	uv run mypy src tests

test:
	uv run pytest

coverage:
	uv run pytest --cov=credlens --cov-report=term-missing

run:
	uv run credlens $(ARGS)

doctor:
	uv run credlens doctor

ci: lint format-check typecheck test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml .coverage
