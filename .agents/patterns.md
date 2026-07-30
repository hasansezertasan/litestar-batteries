# Project Patterns

> Ralph-style consolidated learnings extracted from completed tracks.
> Read this file before starting new work to prime context.
> Update this file at phase/track completion with elevated patterns.

<!-- truth: start -->
## Code Conventions

- **Canonical verify (run before every commit):** `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pyright && uv run pytest` (bare `mypy`/`pyright` honor `files`/`include` = src+tests).
- **Strict typing everywhere:** mypy `strict=true` **and** pyright `strict`; the package ships `py.typed`. Under `tests/`, pyright's `reportUnknownVariableType`/`reportUnknownMemberType` are disabled (via a `[[tool.pyright.executionEnvironments]]` entry) because Litestar's `create_test_client` has a broad, partially-inferred signature — `src` stays fully strict.
- **Coverage gate is hard:** `--cov-fail-under=80` lives in `[tool.pytest.ini_options].addopts`; new code must carry tests that keep coverage ≥80%.
- **Package version:** resolved at runtime via `importlib.metadata.version("litestar-batteries")` (fallback `"0.0.0"` guarded with `# pragma: no cover`), not hardcoded.
- **Dev deps** live in `[dependency-groups].dev`; `uv sync` installs them + the package (editable). Anything imported directly in `src` is a **direct** `dependencies` entry (e.g. `msgspec`), never relied on transitively.

## Architecture

- **Library, not app/CLI:** no `[project.scripts]` entrypoint. Runtime deps: `litestar>=2,<3` and `msgspec` (both direct; msgspec used for response models).
- **CI mirrors local exactly:** `.github/workflows/ci.yml` runs the same five commands; jobs = lint / typecheck / test(matrix 3.10 & 3.14). Uses `actions/checkout@v7` + `astral-sh/setup-uv@v9.0.0` (setup-uv has **no floating major tag** — pin the full version), and `uv sync --frozen` for reproducible installs against the committed `uv.lock`.
- **Battery pattern (established by health-battery):** each battery ships as a Litestar **`InitPlugin`** taking a dataclass `*Config`. The plugin's sync `on_app_init(app_config)` appends handlers to `app_config.route_handlers`. Configurable route via a `path` field; dynamic status via `Response(content, status_code=...)`, and **declare non-inferred status codes** with `responses={code: ResponseSpec(...)}` so they appear in the OpenAPI schema. `str`-enum fields use `Literal[...]`. Public API re-exported from `litestar_batteries.__init__`. Layout: `litestar_batteries/<battery>/{models,controller,plugin}.py`.
- **Verify external API before planning:** confirm current Litestar (or any lib) API via Context7 + `gh api .../releases/latest`; also confirm a pinned action tag actually exists via `git ls-remote` (a `releases/latest` full tag ≠ a floating `@vN` major tag). `litestar.plugins.InitPlugin.on_app_init` is **sync**.

## Gotchas

- **Flow's pre-commit hook crashes on Python < 3.10:** the shipped `.git/hooks/pre-commit` uses `str | None` / `list[dict]` annotations evaluated at def time; under a system `python3` of 3.9 it raises `TypeError` and silently blocks the commit. Fix: add `from __future__ import annotations` at the top of the hook. The upstream plugin template still has the bug.
- **No auto-sync from Beads → spec.md here:** `spec.md` markers are updated manually via `/flow:sync` (Flow's Beads→spec auto-sync is not relied upon in this repo). The committed `.beads/issues.jsonl` ledger — not the ignored `.beads/embeddeddolt` cache — is the **source of truth**.
- **`uv run "cmd --flag"` fails:** pass args unquoted (`uv run cmd --flag`); a single quoted string is treated as one executable name.
- **PyYAML reads workflow `on:` as boolean `True`** (YAML 1.1); GitHub's parser is fine. Don't "fix" it.
- **Ignore policy is hybrid:** `.agents/` (docs/patterns/knowledge/archive) is committed to git. Under `.beads/`, the binary embedded-Dolt store is git-ignored (local cache) but the `.beads/issues.jsonl` export **is** git-tracked (`.beads/*` + `!.beads/issues.jsonl`) and is the portable source of truth — no Dolt remote. Keep `CLAUDE.md` self-authoritative anyway so the repo builds/verifies without any Flow context.
- **Python 3.10 is in the CI matrix → no 3.11+ stdlib APIs in `src`:** typers pin `pythonVersion = "3.10"`
  and tests run on 3.10, but neither necessarily flags a 3.11-only *runtime* call. Prefer the
  3.10-compatible form — e.g. the `asyncio.timeout()` context manager is 3.11+, so bound awaits with
  3.10-safe primitives instead. `asyncio.TimeoutError` is importable on 3.10 (a distinct class there)
  and is an alias of builtin `TimeoutError` on 3.11+. (from: health-timeout)
- **Bounding an await ≠ distinguishing your deadline from the awaited code's own timeout:** `asyncio.wait_for`
  raises `asyncio.TimeoutError` for *its* deadline, but a coroutine that raises `asyncio.TimeoutError`
  itself (an upstream client timeout) surfaces as the *same type* — so `except asyncio.TimeoutError`
  around `wait_for` conflates them and discards the real error. When both can occur, detect the deadline
  by **mechanism**: run the coroutine as a task, `await asyncio.wait({task}, timeout=...)`, treat "still
  pending" as your timeout (cancel it, raise a private sentinel), and `task.result()` to re-raise the
  coroutine's own exception unchanged. (from: health-timeout, PR #8 review)
- **msgspec empty-literal defaults are per-instance-safe:** `checks: list[X] = []` on a `msgspec.Struct` does NOT share state (msgspec treats empty `[]`/`{}`/`set()` as an implicit factory). Do not "fix" it to `msgspec.field(default_factory=list)` — bare `list` trips pyright strict (`list[Unknown]`). (The plain-dataclass mutable-default rule does not apply to Structs.)

## Skill Associations

### Cross-Cutting (Use Across All Domains)

| Domain | Recommended Skill | When to Use |
|--------|-------------------|-------------|
| Security | `flow:security-auditor` | Auth, input handling, secrets, API keys |
| Architecture | `flow:architecture-critic` | New modules, boundary changes, coupling |
| Performance | `flow:performance-analyst` | Hot paths, DB queries, loops, caching |
| Decision Making | `flow:consensus` | Choosing between A/B approaches |
| Challenge Claims | `flow:challenge` | Reviewing assertions, preventing bias |
| Deep Analysis | `flow:deepthink` | Resistant problems, shallow analysis |
| Code Tracing | `flow:tracer` | Execution paths, call chains, data flow |
| Multiple Viewpoints | `flow:perspectives` | Trade-offs, risk assessment, pros/cons |
| Devil's Advocate | `flow:devils-advocate` | PR review, design proposals, pushback |
| Documentation | `flow:docgen` | API docs, module docs, reference guides |
| API/Framework Lookup | `flow:apilookup` | External docs, versions, breaking changes |

### Languages & Frameworks

| Domain | Recommended Skill | When to Use |
|--------|-------------------|-------------|
| Python | `flow:python` | .py files, pyproject.toml, uv, ruff, mypy |
| Rust | `flow:rust` | .rs files, Cargo.toml, FFI (PyO3/napi-rs) |
| C++ | `flow:cpp` | .cpp/.hpp files, CMakeLists.txt |
| Mojo | `flow:mojo-tools` | .mojo files, SIMD, Python interop |
| Bash | `flow:bash` | .sh files, shell scripts |
| Litestar | `flow:litestar` | Route handlers, guards, middleware, DTOs |
| React | `flow:react` | .tsx/.jsx, hooks, server components |
| Vue | `flow:vue` | .vue files, Composition API |
| Svelte | `flow:svelte` | .svelte files, runes ($state, $derived) |
| Angular | `flow:angular` | angular.json, signals, standalone components |
| Tailwind/Shadcn | `flow:tailwind` / `flow:shadcn-tools` | Utility classes, cn(), Radix primitives |
| Railway | `flow:railway-tools` | Railway deployment, services, databases |
<!-- truth: end -->

---

## Pattern Sources

<!-- Track which tracks contributed patterns -->

| Pattern | Source Track | Date |
|---------|--------------|------|
