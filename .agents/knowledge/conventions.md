# Conventions

Current-state reference for tooling, typing, testing, and CI. Read alongside `patterns.md`.

## Toolchain (all via `uv`)

Dev tools live in `[dependency-groups].dev`: `ruff`, `mypy`, `pyright`, `pytest`, `pytest-cov`.
`uv sync` installs them plus the package (editable).

**Canonical verify** (identical locally and in CI):

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pyright && uv run pytest
```

- `ruff`: line-length 100, target `py310`, lint select `E,F,I,UP,B,SIM,TC,RUF`.
- Run `mypy`/`pyright` with **no path** so they honor config (`files`/`include` = `["src","tests"]`).
  Passing `mypy src` silently skips tests — don't.

## Typing (strict, `py.typed`)

- mypy `strict=true`, pyright `typeCheckingMode="strict"`, both pinned to `pythonVersion/python_version = "3.10"`.
- **`src` is fully strict.** Under `tests/`, a `[[tool.pyright.executionEnvironments]]` entry with
  `root="tests"` disables `reportUnknownVariableType` and `reportUnknownMemberType`, because Litestar's
  `create_test_client` has a huge partially-inferred signature that trips strict "unknown type"
  reporting. This is the minimal override — everything else stays strict.
- Any module imported directly in `src` must be a **direct** `dependencies` entry (e.g. `msgspec`),
  never relied on transitively via litestar.

## Testing

- `pytest` + `pytest-cov`; hard gate `--cov-fail-under=80` in `[tool.pytest.ini_options].addopts`;
  branch coverage on; coverage source = `litestar_batteries`.
- Handler/plugin tests use Litestar's **sync** `create_test_client(route_handlers=[], plugins=[...])`
  (no async-test plugin needed). Assert status codes and the JSON body shape.
- TDD: write the failing test first (Red), confirm it fails for the right reason, then implement (Green).

## CI (`.github/workflows/ci.yml`)

- Triggers: `push` to `main` + `pull_request`; concurrency-cancels in-progress runs.
- Jobs: `lint` (ruff check + format), `typecheck` (mypy + pyright), `test` (matrix Python **3.10 &
  3.14**, `fail-fast: false`). Mirrors the local canonical verify exactly.
- Actions: `actions/checkout@v7`, `astral-sh/setup-uv@v9.0.0`. **setup-uv has no floating major tag**
  — pin the full version; verify any action tag exists with `git ls-remote` before pinning.
- All jobs run `uv sync --frozen` for reproducible installs; the committed `uv.lock` must be kept in
  sync (regenerate with `uv lock` and commit whenever `dependencies` change, or `--frozen` fails).

## Packaging & versioning

- `uv_build` backend, `src/` layout, `py.typed` shipped in the wheel.
- `__version__` resolved at runtime via `importlib.metadata.version("litestar-batteries")`, with a
  `PackageNotFoundError` fallback to `"0.0.0"` marked `# pragma: no cover`.
- Library, not app: no console-script entrypoint.

## Repo/harness notes

- **Ignore policy (hybrid):** `.agents/` (Flow planning docs, patterns, knowledge, archive) is
  **committed** to git; the Beads DB (`.beads/`) is git-ignored and syncs via a Dolt remote instead.
  `CLAUDE.md` is still kept self-authoritative so the repo builds without any Flow context.
- Beads (`bd`) uses a dolt-embedded backend; the DB lives at `<project>/.beads/embeddeddolt`. The Flow
  auto-sync git hook is a no-op here (it keys off a `.beads/` dir next to `.agents/`, which this layout
  doesn't have), so `spec.md` markers are maintained manually — **Beads is the source of truth**.
- **Beads Dolt remote:** `https://doltremoteapi.dolthub.com/hasansezertasan/litestar-batteries-beads`
  ([web UI](https://www.dolthub.com/repositories/hasansezertasan/litestar-batteries-beads)). Sync task
  state across machines with `bd dolt push` / `bd dolt pull` (`sync.remote` is configured locally).
- **Restore Beads on a fresh clone / new machine** (verified end-to-end):
  ```bash
  # after `git clone` (which brings .agents/) and installing bd + dolt, from the repo root:
  bd init --remote https://doltremoteapi.dolthub.com/hasansezertasan/litestar-batteries-beads \
    --non-interactive --skip-agents          # clones the task DB from the remote into .beads/
  bd stats                                     # expect the full issue history (15+ issues)
  ```
  Note: `bd init --remote` is the correct entry point on a fresh clone — `bd config set` / `bd bootstrap`
  fail there because no workspace exists yet. `--skip-agents` avoids writing a harness `AGENTS.md`.
- Commits follow Conventional Commits; branches Conventional Branch; PR titles Conventional PR.
