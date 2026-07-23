# Flow File Index

> Resolution index for Flow context files. Load these to prime an agent.

## Core Context (load first)

| File | Purpose | Priming |
|------|---------|---------|
| [product.md](product.md) | What we're building and why | Always (truth block) |
| [tech-stack.md](tech-stack.md) | Languages, frameworks, tools | Always (truth block) |
| [product-guidelines.md](product-guidelines.md) | Tone, API design, doc rules | On demand |
| [workflow.md](workflow.md) | Commands, TDD lifecycle, quality gates | Always (truth block) |
| [patterns.md](patterns.md) | Elevated, reusable project patterns | Always |

## Knowledge Base

| File | Purpose |
|------|---------|
| [knowledge/index.md](knowledge/index.md) | Synthesized learnings from completed flows |

## Registries

| File | Purpose |
|------|---------|
| [flows.md](flows.md) | Registry of all flows and their status |
| [beads.json](beads.json) | Beads backend configuration (Dolt-synced; DB git-ignored) |

## Code Styleguides

| File | Applies To |
|------|-----------|
| [code-styleguides/python.md](code-styleguides/python.md) | All Python code |
| [code-styleguides/litestar.md](code-styleguides/litestar.md) | Litestar handlers, DI, DTOs, middleware |
| [code-styleguides/testing.md](code-styleguides/testing.md) | Tests |

## Task Memory

Beads (`bd`, dolt embedded backend) is the source of truth for task state.
Run `bd prime` at session start; run `/flow:sync` after Beads mutations.
