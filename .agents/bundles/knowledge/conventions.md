---
type: Guide
title: Conventions
description: Toolchain, strict typing, testing, CI, packaging, and repository/harness conventions.
tags: [conventions, tooling, ci, typing]
---

# Conventions

Current-state reference for tooling, typing, testing, and CI. Read alongside [patterns/](patterns/index.md).

## Toolchain (all via `uv`)

Dev tools live in `[dependency-groups].dev`: `ruff`, `mypy`, `pyright`, `pytest`, `pytest-cov`.
`uv sync` installs them plus the package (editable).

**Canonical verify** (identical locally and in CI):

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pyright && uv run pytest
```

- `ruff`: line-length 100, target `py310`, lint select `E,F,I,UP,B,SIM,TC,RUF`.
- Run `mypy`/`pyright` with **no path** so they honor config (`files`/`include` = `["src","tests"]`).
  Passing `mypy src` silently skips tests — don't.

## Typing (strict, `py.typed`)

- mypy `strict=true`, pyright `typeCheckingMode="strict"`, both pinned to `pythonVersion/python_version = "3.10"`.
- **`src` is fully strict.** Under `tests/`, a `[[tool.pyright.executionEnvironments]]` entry with
  `root="tests"` disables `reportUnknownVariableType` and `reportUnknownMemberType`, because Litestar's
  `create_test_client` has a huge partially-inferred signature that trips strict "unknown type"
  reporting. This is the minimal override — everything else stays strict.
- Any module imported directly in `src` must be a **direct** `dependencies` entry (e.g. `msgspec`),
  never relied on transitively via litestar.

## Testing

- `pytest` + `pytest-cov`; hard gate `--cov-fail-under=80` in `[tool.pytest.ini_options].addopts`;
  branch coverage on; coverage source = `litestar_batteries`.
- Handler/plugin tests use Litestar's **sync** `create_test_client(route_handlers=[], plugins=[...])`
  (no async-test plugin needed). Assert status codes and the JSON body shape.
- TDD: write the failing test first (Red), confirm it fails for the right reason, then implement (Green).

## CI (`.github/workflows/ci.yml`)

- Triggers: `push` to `main` + `pull_request`; concurrency-cancels in-progress runs.
- Jobs: `lint` (ruff check + format), `typecheck` (mypy + pyright), `test` (matrix Python **3.10 &
  3.14**, `fail-fast: false`). Mirrors the local canonical verify exactly.
- Actions are **pinned by commit SHA** with a version comment (e.g. `astral-sh/setup-uv@<sha> # v10.2.0`);
  Renovate keeps them current. setup-uv has no floating major tag — verify any tag exists with
  `git ls-remote` before pinning.
- All jobs run `uv sync --frozen` for reproducible installs; the committed `uv.lock` must be kept in
  sync (regenerate with `uv lock` and commit whenever `dependencies` change, or `--frozen` fails).

## Packaging & versioning

- `uv_build` backend, `src/` layout, `py.typed` shipped in the wheel.
- `__version__` resolved at runtime via `importlib.metadata.version("litestar-batteries")`, with a
  `PackageNotFoundError` fallback to `"0.0.0"` marked `# pragma: no cover`.
- Library, not app: no console-script entrypoint.

## Repo/harness notes

- **Flow planning context** lives in OKF v0.2 bundles under `.agents/bundles/` and is committed to git
  (shared policy). Task state is the Markdown task files under `.agents/bundles/specs/<flow_id>/tasks/`;
  there is no task database or tracker CLI. Transaction journals (`.agents/transactions/`) and task
  scratch (`.agents/scratch/`) are git-ignored crash-recovery state.
- Completed flows are synthesized into these knowledge chapters, logged once in
  [`log.md`](../log.md), and their spec directories removed — git history is the archive.
- `AGENTS.md` stays self-authoritative so the repo builds and verifies without any Flow context.
- Renovate maintains dependency and action pins.
- Commits follow Conventional Commits; branches Conventional Branch; PR titles Conventional PR.
