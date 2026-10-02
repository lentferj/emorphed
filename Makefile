.PHONY: lint format typecheck test audit check

# No-AI quality gate. Run `uv sync` first, then either activate the venv
# or prefix with `uv run`. `check` runs every stage in sequence and stops
# at the first failure.

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .

typecheck:
	mypy emorphed emu tests

test:
	pytest

audit:
	pip-audit
	vulture emorphed emu tests
	deptry .
	detect-secrets audit .secrets.baseline

check: lint typecheck test audit
