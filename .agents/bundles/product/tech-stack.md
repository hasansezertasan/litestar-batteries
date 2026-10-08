---
type: Guide
title: Tech Stack
description: Language, framework, packaging, and tooling choices for litestar-batteries.
tags: [tech-stack, python, tooling]
---

# Tech Stack

<!-- truth: start -->
- **Language:** Python (`requires-python = ">=3.10"`); CI matrix 3.10 & 3.14
- **Framework:** Litestar — runtime dependencies `litestar>=2,<3` and `msgspec` (both direct)
- **Package manager:** `uv` (`uv.lock` committed; CI uses `uv sync --frozen`)
- **Build backend:** `uv_build` (`>=0.12.0,<0.13.0`)
- **Packaging:** `src/` layout, `litestar_batteries` package, typed (`py.typed`), MIT license (PEP 639 `license` + `license-files`)
- **Tooling:** ruff, mypy (strict), pyright (strict), pytest + pytest-cov (80% gate)
<!-- truth: end -->

## Configured Tooling

Declared in `[dependency-groups].dev` + `[tool.*]` of `pyproject.toml`:

- **Lint & format:** `ruff` (line-length 100, target py310, lint select `E,F,I,UP,B,SIM,TC,RUF`)
- **Type checking:** `mypy` (strict, `files=["src","tests"]`) **and** `pyright` (strict, `include=["src","tests"]`)
- **Testing:** `pytest` + `pytest-cov`, hard `--cov-fail-under=80` gate, branch coverage on
- **Canonical verify:** `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pyright && uv run pytest`

## Testing Notes

- Handler/plugin tests use Litestar's sync `create_test_client`; middleware tests that need
  concurrency use `AsyncTestClient`.
- `pyright` runs strict on `src`; under `tests/` the `reportUnknownVariableType` /
  `reportUnknownMemberType` rules are disabled because Litestar's `create_test_client` has a broad,
  partially-inferred signature.

## Candidate tooling (not yet added)

- `polyfactory` for test data when useful.

## Change Policy

Any tech-stack change is documented **here first**, before implementation (Document-Driven Development).
