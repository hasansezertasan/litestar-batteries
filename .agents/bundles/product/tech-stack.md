---
type: Guide
title: Tech Stack
description: Language, framework, packaging, and tooling choices for litestar-batteries.
tags: [tech-stack, python, tooling]
---

# Tech Stack

<!-- truth: start -->
- **Language:** Python (`requires-python = ">=3.10"`); tox envs across 3.10–3.14
  (full range on Linux; default interpreter on macOS/Windows)
- **Framework:** Litestar — runtime dependencies `litestar>=2.19,<3`, `msgspec`,
  and `typing_extensions` (for `@override` markers on framework subclass hooks;
  stdlib `typing.override` needs 3.12). All three are direct and documented.
- **Package manager:** `uv` (`uv.lock` committed; everything runs `--locked`)
- **Build backend:** `hatchling` + `hatch-vcs` (version dynamic, derived from Git
  tags; release-please owns tagging and `CHANGELOG.md`)
- **Packaging:** `src/` layout, `litestar_batteries` package, typed (`py.typed`),
  MIT license
- **Tooling:** ruff (lint `ALL` + format), mypy (strict), basedpyright/ty/pyrefly/
  zuban (zero-warning gates), pylint (always-on), pytest + coverage (99% gate),
  all orchestrated via `tox`; git hooks via `prek`
<!-- truth: end -->

## Configured Tooling

Declared in `[dependency-groups]` + `[tool.*]` of `pyproject.toml`:

- **Lint & format:** `ruff` (line-length 88, `fix=true` + `unsafe-fixes=true`,
  `select=ALL`, preview rules on). Gate with `ruff check --diff` before letting
  it fix: the first fix pass rewrites `src/**` in place.
- **Type checking:** `mypy` strict (runs for 3.10, 3.14, win32, darwin),
  `basedpyright`, `ty`, `pyrefly`, `zuban` — all must be fully clean, including
  zero warnings (basedpyright warnings fail the gate).
- **Testing:** `pytest` (+ `pytest-xdist`, `-m <component>` markers via
  `tests/conftest.py`), branch coverage with a hard `fail_under=99` gate;
  the root `README.md` snippets run as doctests.
- **Architecture:** `import-linter` exhaustive layers contract — each battery is
  an independent sibling layer (`health | idempotency | secure_headers`); new batteries extend it.
- **Docs:** Sphinx (Shibuya theme) with a warning-allowlist gate, doctest
  builder, and versioned GitHub Pages deploys.
- **Canonical verify:** `uv run --locked tox run` (style + doctest + version
  matrix); fast single file: `uv run --locked pytest tests/test_smoke.py -v`;
  hooks: `uv run --locked tox run -e prek`.

## Testing Notes

- Handler/plugin tests use Litestar's sync `create_test_client`; middleware tests
  that need concurrency use `AsyncTestClient` or drive `middleware.handle`
  directly with ASGI test doubles.
- Async test doubles keep `async` shape (the interface requires it) with an
  `await asyncio.sleep(0)` where they otherwise would not await; Litestar
  injects handler params by name, so unused body params are dropped, not renamed.
- Test-only dependencies stay in the `test` group; ASGI message literals that
  exceed litestar's event types use `cast("Message", ...)` at the call site.

## Candidate tooling (not yet added)

- `polyfactory` for test data when useful.

## Change Policy

Any tech-stack change is documented **here first**, before implementation (Document-Driven Development).
