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
**local cache** and is git-ignored; the git-tracked **source of truth** is the JSONL export
(`.beads/issues.jsonl`), committed with the rest of `.agents/`. A fresh clone rebuilds the local DB with
`bd init` then `bd import` (see Task Memory below). There is **no external service / Dolt remote** —
history lives in git. This file remains self-sufficient for building and verifying regardless.

## Task Memory

The committed `.beads/issues.jsonl` ledger is the **source of truth** for task state; `bd`'s embedded
Dolt store (`.beads/embeddeddolt`) is only a git-ignored local cache of it — no external service or
Dolt remote.

- Run `bd prime` at session start. On a fresh clone, restore the local DB from the committed ledger:
  `bd init`, then `bd dolt remote remove origin 2>/dev/null || true` (enforce local-only — `bd init` may
  auto-add the git origin as a Dolt remote), then `bd config set export.auto true` and
  `bd config set export.path issues.jsonl` (re-apply auto-export; it is not carried in the JSONL), then
  `bd import`. Thereafter `bd` auto-exports to `.beads/issues.jsonl` after writes, but that export is
  throttled and omits `bd remember` memories / infra beads — so **before committing run
  `bd export --all -o .beads/issues.jsonl`** to guarantee a fresh, complete ledger, then commit it (e.g.
  via `/flow:sync`) so task history stays versioned in git.
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
