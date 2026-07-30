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

Task state lives in **Beads** (`bd`). The binary embedded-Dolt store (`.beads/embeddeddolt`) is a
**local cache** and is git-ignored; the git-tracked source of truth is the JSONL export
(`.beads/issues.jsonl`), committed with the rest of `.agents/`. A fresh clone rebuilds the DB from it
with `bd import`. There is **no external service / Dolt remote** — history lives in git. This file
remains self-sufficient for building and verifying regardless.

## Task Memory

Beads (`bd`, embedded Dolt engine) is the source of truth for task state. The binary Dolt store is a
local cache (git-ignored); the committed `.beads/issues.jsonl` export is what travels in git — no
external service or Dolt remote.

- Run `bd prime` at session start. On a fresh clone, `bd init` then `bd import` rebuilds the local DB
  from the committed `.beads/issues.jsonl`. `bd` auto-exports to that file after writes (`export.auto`);
  commit it (e.g. via `/flow:sync`) so task history is versioned in git.
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
