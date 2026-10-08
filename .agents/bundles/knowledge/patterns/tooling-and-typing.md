---
type: Pattern
title: Tooling and Typing Patterns
description: Canonical verify command, strict typing rules, coverage gate, and dependency hygiene.
tags: [tooling, typing, python]
---

# Tooling and Typing Patterns

- **Canonical verify (run before every commit):** `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pyright && uv run pytest`. Run bare `mypy`/`pyright` so they honor `files`/`include` = src+tests; `mypy src` silently skips tests.
- **Strict typing everywhere:** mypy `strict=true` and pyright `strict`; the package ships `py.typed`. Under `tests/`, pyright's `reportUnknownVariableType`/`reportUnknownMemberType` are disabled (a `[[tool.pyright.executionEnvironments]]` entry) because Litestar's `create_test_client` has a broad, partially-inferred signature — `src` stays fully strict.
- **Prefer an inline `# pyright: ignore[rule]` at the exact site** (e.g. a white-box private import in a test) over relaxing a rule for a whole directory.
- **Avoid partially-unknown library returns under strict:** e.g. read a response's content-type by scanning the raw ASGI `http.response.start` headers rather than `MutableScopeHeaders.get`, which pyright reports as partially unknown.
- **Coverage gate is hard:** `--cov-fail-under=80` lives in `[tool.pytest.ini_options].addopts`; new code carries tests that keep coverage ≥ 80%.
- **Package version** resolves at runtime via `importlib.metadata.version("litestar-batteries")` (fallback `"0.0.0"` under `# pragma: no cover`), not hardcoded.
- **Direct dependencies only:** anything imported in `src` is a direct `dependencies` entry (e.g. `msgspec`), never relied on transitively through litestar. Dev tools live in `[dependency-groups].dev`.
- **`uv run "cmd --flag"` fails:** pass args unquoted (`uv run cmd --flag`); a single quoted string is treated as one executable name.
- **PyYAML reads a workflow's `on:` key as boolean `True`** (YAML 1.1); GitHub's parser is fine. Don't "fix" it.
