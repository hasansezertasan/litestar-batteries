# Tech Stack

<!-- truth: start -->
- **Language:** Python (`requires-python = ">=3.10"`)
- **Framework:** Litestar — **runtime dependency** `litestar>=2,<3` (msgspec ships transitively)
- **Package manager:** `uv`
- **Build backend:** `uv_build` (>=0.11.31,<0.12.0)
- **Packaging:** `src/` layout, `litestar_batteries` package, typed (`py.typed`)
<!-- truth: end -->

## Detected From Repo

| Item | Source | Value |
|------|--------|-------|
| Project name | `pyproject.toml` | `litestar-batteries` |
| Python requirement | `pyproject.toml` | `>=3.10` |
| Build backend | `pyproject.toml` | `uv_build` |
| Runtime dependency | `pyproject.toml` | `litestar>=2,<3` (added by the health-battery flow) |

## Testing Notes

- Handler/plugin tests use Litestar's sync `create_test_client` (no async-test plugin needed).
- `pyright` runs strict on `src`; under `tests/` the `reportUnknownVariableType` /
  `reportUnknownMemberType` rules are disabled because Litestar's `create_test_client` has a broad,
  partially-inferred signature. `src` stays fully strict.

## Configured Tooling

Wired in Chapter `local-tooling` (2026-07-23), in `[dependency-groups].dev` + `[tool.*]` of `pyproject.toml`:

- **Lint & format:** `ruff` (line-length 100, target py310, lint select `E,F,I,UP,B,SIM,TC,RUF`)
- **Type checking:** `mypy` (strict, `files=["src","tests"]`) **and** `pyright` (strict, `include=["src","tests"]`)
- **Testing:** `pytest` + `pytest-cov`, with a **hard `--cov-fail-under=80`** gate; branch coverage on
- **Canonical verify:** `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pyright && uv run pytest`

### Candidate tooling (not yet added)

- **Property/data:** `polyfactory` for test data when useful
- **Handler tests:** Litestar `TestClient` (arrives with the first battery that adds Litestar)

## Resolved Inconsistencies

- **[2026-07-23] Python version aligned:** `requires-python` relaxed `>=3.14` → `>=3.10` in
  `pyproject.toml` to match the `3.10` floor in `.python-version`.
- **[2026-07-23] Console script removed:** dropped the `[project.scripts]` entry and the
  placeholder `main()` — litestar-batteries is a library, not a CLI, so no entrypoint is needed.

## Change Policy

Per `workflow.md`, any tech-stack change must be documented **here first**, with a dated note, before
implementation.
