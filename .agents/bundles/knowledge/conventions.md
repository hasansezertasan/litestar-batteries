---
type: Guide
title: Conventions
description: Toolchain, strict typing, testing, CI, packaging, and repository/harness conventions.
tags: [conventions, tooling, ci, typing]
---

# Conventions

Current-state reference for tooling, typing, testing, and CI. Read alongside [patterns/](patterns/index.md).

## Toolchain (all via `uv`)

Tooling lives in `[dependency-groups]` (`dev`, `style`, `test`, `docs`, `prek`,
...). `uv sync` installs the default set plus the package (editable); every
invocation below uses `--locked` for reproducible installs.

**Canonical verify** (identical locally and in CI):

```bash
uv run --locked tox run                 # style + docs-doctest + version matrix + floor
uv run --locked tox run -e style        # ruff, 5 type checkers, pylint, slotscheck, ...
uv run --locked tox run -e prek         # git hooks (prek)
uv run --locked pytest tests/test_smoke.py -v   # one file, fast
```

- `ruff`: line-length 88, lint `select=ALL` with `fix=true` + `unsafe-fixes=true`.
  Run `ruff check --diff` (or `--no-fix`) before any fix pass: auto-fix rewrites
  `src/**` in place. `ruff format` also normalizes Python snippets in `.md` files.
- Markdown prose is additionally gated by `markdownlint-cli2` (`fix:true`, run via
  prek). It must never touch `.agents/**`: its autofix has deleted content from
  agent workspace files before, so `.markdownlint-cli2.jsonc` ignores that tree
  (see the comment there) — ruff-format remains the only formatter for it.
- Run `mypy`/`basedpyright` with **no path** so they honor config; `mypy` covers
  `src` + `docs/examples` (not `tests`), while `ty` also covers `tests`.

## Typing (strict, `py.typed`)

- mypy `strict=true`, basedpyright/ty/pyrefly/zuban fully clean with zero
  warnings, all pinned to Python 3.10 semantics.
- **`src` avoids `Any` in annotations.** Litestar leaves user/auth/state generics
  to the application, so the single `AnyRequest = Request[Any, Any, Any]` alias
  (in `idempotency/models.py`) keeps the intentionally-untyped request form in
  one documented place. Framework-overriding methods carry `@override`.
- Litestar's ASGI event `TypedDict`s omit extension keys (e.g. `trailers`) and
  complain about partial-union access: read optional message fields through
  narrowed event types (`message["type"]` discrimination), never through a
  `Mapping` view or a parenthesized `Literal` (parens change `Literal` semantics
  and break type checkers — both carry a comment where the linter disagrees).
- Any module imported directly in `src` must be a **direct** `dependencies` entry
  (e.g. `msgspec`, `typing_extensions`), never relied on transitively via litestar.

## Testing

- `pytest`; hard gate `fail_under=99` (branch coverage on); coverage source =
  `litestar_batteries` + `tests`. Untestable-by-construction code (unreachable
  defensive invariants, protocol stubs never called directly) carries
  `# pragma: no cover`, never a blanket pattern.
- Handler/plugin tests use Litestar's **sync** `create_test_client(route_handlers=[], plugins=[...])`
  (no async-test plugin needed). Assert status codes and the JSON body shape.
- Every test function has a one-line imperative docstring (D103); nested ASGI
  doubles stay docstring-free with `sleep(0)` awaits and `_`-prefixed unused
  params (positional call sites only — keyword-injected names are never renamed).
- TDD: write the failing test first (Red), confirm it fails for the right reason, then implement (Green).

## CI (`.github/workflows/ci.yml`)

- Triggers: `push` to `main`/`master` + `pull_request` (draft-gated);
  concurrency-cancels in-progress runs.
- Jobs: `changes` (path filter), `hooks` (prek), `style` (the full
  lint/type/docs-lint battery), `docs-doctest`, `test-core` (tox version matrix
  per OS). Mirrors the local canonical verify exactly.
- The ubuntu `test-core` cell also runs the `floor` env (litestar 2.15.0 on
  Python 3.10, via `uv-venv-runner` instead of the lock runner); its `deps` pin
  and `commands_pre` version assertion mirror the `[project]` `litestar` lower
  bound and change together with it.
- Actions are **pinned by commit SHA** with a version comment;
  Renovate keeps them current.
- All jobs run `uv sync --locked` for reproducible installs; the committed
  `uv.lock` must be kept in sync (regenerate with `uv lock`/`uv add` and commit
  whenever `dependencies` change).

## Packaging & versioning

- `hatchling` + `hatch-vcs` backend, `src/` layout, `py.typed` shipped in the wheel.
- `__version__` resolved at runtime via `importlib.metadata.version("litestar-batteries")`
  in `src/litestar_batteries/_version_fallback.py`, with a `"0.0.0"` fallback
  marked `# pragma: no cover`. (`_version.py` is hatch-vcs-generated — never edit it.)
- Versions come from Git tags via release-please — do not hand-edit a version
  literal anywhere (including `.github/release-please-manifest.json`).
- Library, not app: no console-script entrypoint (`python -m` exits non-zero
  with an explanatory message by template contract).

## Repo/harness notes

- **Flow planning context** lives in OKF v0.2 bundles under `.agents/bundles/` and is committed to git
  (shared policy). Task state is the Markdown task files under `.agents/bundles/specs/<flow_id>/tasks/`;
  there is no task database or tracker CLI. Transaction journals (`.agents/transactions/`) and task
  scratch (`.agents/scratch/`) are git-ignored crash-recovery state.
- Completed flows are synthesized into these knowledge chapters, logged once in
  [`log.md`](../log.md), and their spec directories removed — git history is the archive.
- `AGENTS.md` stays self-authoritative so the repo builds and verifies without any Flow context.
- Renovate maintains dependency and action pins.
- Commits follow Conventional Commits; branches Conventional Branch; PR titles Conventional PR.
