.PHONY: lint format typecheck test audit check test-hardware

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

# --- hardware ----------------------------------------------------------------

# The hardware suite is a separate target, not part of `check`: CLAUDE.md's
# rule is that only one session drives a unit at a time, and CI -- which
# runs `make check` -- must not be it. `--hardware` and EMORPHED_HARDWARE=1
# open the ports; without them every test in the file skips with a reason.
#
# `-o addopts=""` because the ordinary addopts carry --cov with a fail_under
# gate: a hardware-only run measures coverage over the handful of tests that
# just ran and would fail by construction. `-rs -s` so the findings the
# probe prints are actually seen -- a skip reason and the bench observations
# are the output of this target.
.PHONY: test-hardware
test-hardware: ## tests that need a real E-mu Morpheus (opens MIDI ports)
	pytest tests/test_hardware.py --hardware -o addopts="" -p no:cacheprovider -rs -s
