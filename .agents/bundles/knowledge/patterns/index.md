---
type: Index
title: Project Patterns
description: Elevated, reusable patterns and gotchas, grouped by topic. Read before starting new work.
tags: [patterns, conventions]
---

# Project Patterns

<!-- truth: start -->
- Run the canonical verify before every commit: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pyright && uv run pytest`.
- Strict mypy + strict pyright on `src`; 80% coverage gate; Python 3.10 floor — no 3.11+ stdlib APIs in `src`.
- Every battery is a Litestar `InitPlugin` taking a dataclass `*Config`; public API re-exported from `litestar_batteries`.
- Verify external library/action APIs against current sources before planning.
<!-- truth: end -->

| Chapter | Covers |
|---------|--------|
| [tooling-and-typing.md](tooling-and-typing.md) | Canonical verify, strict typing, coverage gate, dependencies, uv gotchas |
| [battery-design.md](battery-design.md) | The battery/`InitPlugin` pattern, OpenAPI status codes, msgspec models, API verification |
| [async-and-asgi.md](async-and-asgi.md) | Python 3.10-safe asyncio, timeouts, cancellation, ASGI middleware event handling |
| [testing.md](testing.md) | Litestar test clients, deterministic concurrency tests, regression-first fixes |
| [ci-and-repo.md](ci-and-repo.md) | CI mirroring local, reproducible installs, self-sufficient harness files |
