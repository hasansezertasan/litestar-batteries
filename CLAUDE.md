# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

**litestar-batteries** — a "batteries-included" utility collection for Litestar applications:
reusable, first-party-flavored plugins and utilities (starting with a health-check plugin) that
reduce boilerplate in production Litestar services. It is a **library** (no CLI), targets
**Litestar 2.x** on **Python 3.10+**, ships `py.typed`, and is managed with `uv`.

## Source of Truth

This repo uses [Flow](https://github.com/cofin/flow) for planning. Its context lives under `.agents/`
(`product.md`, `tech-stack.md`, `workflow.md`, `patterns.md`, `index.md`) and task state in Beads
(`bd`). **These are local-only and not committed**, so a fresh clone won't have them — everything
required to build and verify this project is captured in this file. If `.agents/` is present locally,
read it first; otherwise this file is authoritative.

## Task Memory

Beads (`bd`, dolt embedded backend, local-only) is the source of truth for task state.

- Run `bd prime` at session start.
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
