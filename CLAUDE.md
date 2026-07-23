# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

**litestar-batteries** — a "batteries-included" utility collection for Litestar applications.
See [.agents/product.md](.agents/product.md) for the full definition.

## Source of Truth

Flow drives development here. Read these before starting work:

- **[.agents/product.md](.agents/product.md)** — what we're building and why
- **[.agents/tech-stack.md](.agents/tech-stack.md)** — languages, frameworks, tooling, known inconsistencies
- **[.agents/workflow.md](.agents/workflow.md)** — canonical commands, TDD lifecycle, quality gates
- **[.agents/patterns.md](.agents/patterns.md)** — elevated, reusable project patterns
- **[.agents/index.md](.agents/index.md)** — full file resolution index

## Task Memory

Beads (`bd`, dolt embedded backend, local-only) is the source of truth for task state.

- Run `bd prime` at session start.
- Never hand-edit task markers in spec files — run `/flow:sync` after Beads changes.

## Canonical Commands

```bash
uv sync            # setup
uv run pytest      # test
uv run ruff check .# lint
uv run mypy src    # type check
```

Full verification and the TDD lifecycle live in [.agents/workflow.md](.agents/workflow.md).

## Development Approach

Document-Driven Development: write the docs (the contract) first, then build to match.
Any tech-stack change is documented in `.agents/tech-stack.md` **before** implementation.
