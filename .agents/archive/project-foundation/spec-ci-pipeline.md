# Spec: Chapter 2 — ci-pipeline

> Beads epic: `litestar-batteries-1yk` (parent: `litestar-batteries-52a`). Beads is the source of
> truth for task status. Status: ✅ Complete (2026-07-23).

## Goal

Enforce the exact local verification gate in CI on every push and pull request, across the supported
Python version boundaries.

## Design

`.github/workflows/ci.yml` — triggers on `push` (main) and `pull_request`, with concurrency
cancellation. Three jobs, each using `actions/checkout@v7` + `astral-sh/setup-uv@v9` (cache enabled)
and `uv sync`:

| Job | Steps | Python |
|-----|-------|--------|
| `lint` | `ruff check .`, `ruff format --check .` | default |
| `typecheck` | `mypy src`, `pyright` | default (mypy/pyright pinned to 3.10 target in config) |
| `test` | `pytest` (80% coverage gate via pyproject `addopts`) | matrix: **3.10, 3.14** (`fail-fast: false`) |

The command set is identical to the local canonical verify established in Chapter 1:
`uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pyright && uv run pytest`.

## Tasks

### [x] Task 1 — Add GitHub Actions CI workflow (`litestar-batteries-1yk.1`)

Created `.github/workflows/ci.yml` as above. Commit `a6711f2`.

### [x] Task 2 — Validate CI workflow (`litestar-batteries-1yk.2`)

Validated: YAML parses (jobs `lint`/`typecheck`/`test`, triggers `push`+`pull_request`, matrix
`["3.10","3.14"]`); action tags `checkout@v7` / `setup-uv@v9` resolve to existing releases; CI
commands mirror the local gate; all five gates pass locally on Python 3.10.19. Commit `a6711f2`.

## Notes / Gotchas

- PyYAML reads the `on:` key as boolean `True` (YAML 1.1). GitHub Actions' own parser reads it as the
  string `on` — no change needed; this is the standard idiom.
- `mypy`/`pyright` are pinned to a 3.10 target in `pyproject.toml`, so a single (non-matrix) run is
  sufficient; only `pytest` fans out across the version matrix.
- CI has not yet been observed green on GitHub (requires a push/PR). Validation was local + static.

## Chapter Definition of Done

- [x] `.github/workflows/ci.yml` present and valid.
- [x] Runs lint + both type checkers + tests + coverage gate on push/PR across Python 3.10 & 3.14.
- [x] Commands mirror the Chapter 1 local gate.
