# Spec: Chapter 1 — local-tooling

> Beads epic: `litestar-batteries-axm` (parent: `litestar-batteries-52a`). Beads is the source of
> truth for task status — do **not** hand-edit the checkboxes below; run `/flow:sync` after Beads
> mutations. This is a High-Definition Worksheet: an agent with zero prior context should be able to
> implement it exactly.

## Goal

Wire the local dev toolchain so all five gates pass on a clean checkout:
`ruff check`, `ruff format --check`, `mypy`, `pyright`, `pytest` (with ≥80% coverage).

## Preconditions (verified 2026-07-23)

- `pyproject.toml`: `[project].dependencies = []`, `requires-python = ">=3.10"`, `uv_build` backend.
- `src/litestar_batteries/__init__.py` is **empty**; `src/litestar_batteries/py.typed` exists.
- No `tests/`, no `[dependency-groups]`, no `[tool.*]` config.

## Tasks

### [x] Task 1 — Add dev dependency group + tool config to pyproject.toml (`litestar-batteries-axm.1`)

Append the following blocks to `pyproject.toml` (after the existing `[build-system]` block). Keep
`[project].dependencies = []` unchanged.

```toml
[dependency-groups]
dev = [
    "ruff>=0.6",
    "mypy>=1.11",
    "pyright>=1.1.380",
    "pytest>=8",
    "pytest-cov>=5",
]

[tool.ruff]
line-length = 100
target-version = "py310"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "TC", "RUF"]

[tool.mypy]
python_version = "3.10"
strict = true
files = ["src", "tests"]

[tool.pyright]
include = ["src", "tests"]
pythonVersion = "3.10"
typeCheckingMode = "strict"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=litestar_batteries --cov-report=term-missing --cov-fail-under=80"

[tool.coverage.run]
source = ["litestar_batteries"]
branch = true
```

Then run `uv sync` to materialize the dev group. **Acceptance:** `uv sync` succeeds; `uv run ruff --version`, `uv run mypy --version`, `uv run pyright --version`, `uv run pytest --version` all resolve.

### [x] Task 2 — Add `__version__` to the package (`litestar-batteries-axm.2`)

Replace the empty `src/litestar_batteries/__init__.py` with:

```python
"""litestar-batteries: batteries-included utilities for Litestar."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("litestar-batteries")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = ["__version__"]
```

**Acceptance:** `uv run python -c "import litestar_batteries; print(litestar_batteries.__version__)"`
prints `0.1.0` (the installed version). The `except` branch is coverage-excluded via `# pragma: no cover`.

### [x] Task 3 — Write the smoke test (TDD) (`litestar-batteries-axm.3`) — depends on Task 1, Task 2

Create `tests/__init__.py` (empty) and `tests/test_smoke.py`:

```python
"""Smoke tests for the litestar_batteries package."""

import litestar_batteries


def test_package_importable() -> None:
    assert litestar_batteries is not None


def test_version_is_nonempty_string() -> None:
    assert isinstance(litestar_batteries.__version__, str)
    assert litestar_batteries.__version__
```

**Red first:** if written before Task 2, `test_version_is_nonempty_string` fails (no `__version__`).
After Task 2 it passes. **Acceptance:** `uv run pytest` passes and reports ≥80% coverage (this test
exercises all non-pragma lines of `__init__.py`).

### [x] Task 4 — Run full local verification gate and make it green (`litestar-batteries-axm.4`) — depends on Task 3

Run and fix until all pass:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pyright
uv run pytest
```

**Acceptance:** every command exits 0; `pytest` coverage ≥ 80%. If `ruff format --check` fails, run
`uv run ruff format .` and commit the formatting. This command set is the exact contract Chapter 2's CI
will reproduce.

## Notes / Gotchas

- `pyright` installed via pip pulls a bundled Node runtime on first run; allow network on first `uv run pyright`.
- `importlib.metadata.version("litestar-batteries")` requires the package to be installed — `uv sync`
  installs it (editable) into the project venv, so the version resolves in tests.
- Do not add Litestar here; it is deferred (see prd.md).

## Chapter Definition of Done

- [x] All four tasks closed in Beads with commit references.
- [x] Full local gate green with coverage ≥ 80%.
- [x] `tech-stack.md` "Planned / Recommended Tooling" updated to reflect what is now actually configured.
