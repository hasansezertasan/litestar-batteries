# AGENTS.md

Guidance for coding agents when working in this repository.

## Project

**litestar-batteries** — a "batteries-included" utility collection for Litestar applications:
reusable, first-party-flavored plugins and utilities (starting with a health-check plugin) that
reduce boilerplate in production Litestar services. It is a **library** (no CLI), targets
**Litestar 2.x** on **Python 3.10+**, ships `py.typed`, and is managed with `uv`.

## Source of Truth

This repo uses [Flow](https://github.com/cofin/flow) for planning. Its context is **committed** as an
[OKF v0.2](https://github.com/cofin/flow) bundle under `.agents/bundles/` — read it first:

- `.agents/bundles/product/` — `product.md`, `tech-stack.md`, `product-guidelines.md` (what/why, stack)
- `.agents/bundles/knowledge/` — `architecture.md`, `conventions.md`, `workflow.md` (commands & lifecycle),
  `patterns/` (elevated patterns by topic), `code-styleguides/`
- `.agents/bundles/log.md` — history of completed flows
- `.agents/bundles/index.md` — full bundle index

This file remains self-sufficient for building and verifying regardless.

## Task Memory

Task state lives in plain Markdown task files under `.agents/bundles/specs/<flow_id>/tasks/`, which are
the single authority; `spec.md` holds the synchronized checklist. There is no task database or tracker
CLI. Mutate task state only through Flow lifecycle commands (`/flow:implement`, `/flow:sync`, …) — never
hand-edit checklist markers in `spec.md`. Completed flows are synthesized into `knowledge/`, logged in
`log.md`, and their spec directories removed; git history is the archive.

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
Any tech-stack change is documented before implementation (in `.agents/bundles/product/tech-stack.md`).
