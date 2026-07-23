# PRD: project-foundation

> Master Roadmap (Saga). Source of truth for task state is Beads (epic `litestar-batteries-52a`).

## North Star

A fully wired, CI-enforced development toolchain for the **litestar-batteries** library, so the TDD
workflow and quality gates defined in `.agents/workflow.md` are actually runnable — locally and in CI —
before any battery is written.

## Global Constraints & Decisions

_Decided during PRD grilling on 2026-07-23:_

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Type checking | **Both mypy + pyright**, strict | Mirrors Litestar's own CI; catches divergent inference on a `py.typed` library others depend on. |
| Litestar runtime dep | **Deferred** to first battery | Foundation is pure tooling; keep `[project].dependencies = []`. |
| CI Python matrix | **3.10 + 3.14** | Floor + newest; catches version-boundary issues cheaply. |
| Coverage gate | **Hard 80% from day one** | Enforced via `--cov-fail-under=80`; smoke test must exercise the package to clear it. |
| Package manager / build | `uv` / `uv_build`, `src/` layout, `py.typed` | Already established in the repo. |

**Canonical verification (local mirror of CI):**
```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pyright && uv run pytest
```

## Roadmap (Chapters)

| # | Chapter | Beads Epic | Depends on | Status |
|---|---------|-----------|------------|--------|
| 1 | ✅ **local-tooling** — dev deps + tool config + smoke test, all gates green locally | `litestar-batteries-axm` | — | Planned (spec.md) |
| 2 | ✅ **ci-pipeline** — GitHub Actions running the same gates on the 3.10/3.14 matrix | `litestar-batteries-1yk` | Chapter 1 | Not yet planned |

Chapter 2 is intentionally left unplanned until Chapter 1 is complete (its CI steps must mirror the
exact local commands that Chapter 1 establishes).

## Out of Scope

- Any actual "battery" implementation.
- Adding Litestar or other runtime dependencies.
- Release/publishing automation (PyPI), docs site, pre-commit hooks — candidates for later flows.

## Definition of Done (Saga)

- [x] Chapter 1: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pyright && uv run pytest` all pass with coverage ≥ 80%.
- [x] Chapter 2: CI is green on push/PR across Python 3.10 and 3.14, enforcing lint + both type checkers + tests + coverage gate.
