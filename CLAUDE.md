# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

**litestar-batteries** — a "batteries-included" utility collection for Litestar applications:
reusable, first-party-flavored plugins and utilities (starting with a health-check plugin) that
reduce boilerplate in production Litestar services. It is a **library** (no CLI), targets
**Litestar 2.x** on **Python 3.10+**, ships `py.typed`, and is managed with `uv`.

## Source of Truth

This repo uses [Flow](https://github.com/cofin/flow) for planning. Its context is **committed** under
`.agents/` — read it first:

- `.agents/product.md`, `.agents/tech-stack.md`, `.agents/workflow.md` — what/why, stack, commands & lifecycle
- `.agents/patterns.md` — elevated, reusable project patterns
- `.agents/knowledge/` — synthesized reference (`architecture.md`, `conventions.md`)
- `.agents/index.md` — full file resolution index

Task state lives in **Beads** (`bd`). The Beads database (`.beads/`) is **not** in git — it syncs via a
Dolt remote (`bd dolt pull`/`push`) — so a fresh clone has the docs but must pull Beads separately.
This file remains self-sufficient for building and verifying regardless.

## Task Memory

Beads (`bd`, dolt embedded backend) is the source of truth for task state. The DB is not committed;
it syncs across machines via a Dolt remote.

- Run `bd prime` at session start. On a fresh clone, `bd bootstrap` / `bd dolt pull` restores history.
- Never hand-edit task markers in spec files — run `/flow:sync` after Beads changes.

## Canonical Commands

```bash
uv sync                     # setup (installs the dev dependency group)
uv run pytest               # test (enforces an 80% coverage gate)
uv run ruff check .         # lint
uv run ruff format --check .  # format check
uv run mypy                 # type check (mypy, strict)
uv run pyright              # type check (pyright, strict)
```

Full canonical verify (mirrors CI across Python 3.10 & 3.14):

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pyright && uv run pytest
```

## Development Approach

Document-Driven Development: write the docs (the contract) first, then build to match.
Any tech-stack change is documented before implementation (in `.agents/tech-stack.md` when Flow is
set up locally).
