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
  **committed** to git. Under `.beads/`, the binary embedded-Dolt store (`.beads/embeddeddolt`) is
  git-ignored (local cache); the **`.beads/issues.jsonl` export is git-tracked** and is the portable
  source of truth. `.gitignore` uses `.beads/*` + `!.beads/issues.jsonl`. `CLAUDE.md` is still kept
  self-authoritative so the repo builds without any Flow context.
- Beads (`bd`) uses the embedded Dolt engine; the DB lives at `<project>/.beads/embeddeddolt`. The Flow
  auto-sync git hook is a no-op here (it keys off a `.beads/` dir next to `.agents/`, which this layout
  doesn't have), so `spec.md` markers are maintained manually — **Beads is the source of truth**.
- **No remote:** task state is versioned in **git via the JSONL export**, not an external service (no
  DoltHub/Dolt remote); `bd dolt push` / `bd dolt pull` are not used (`.agents/beads.json` sets
  `localOnly: true`, `allowDoltPush: false`). `bd` auto-exports to `.beads/issues.jsonl` after writes
  (`export.auto: true`, `export.git-add: false` — commit it yourself via `/flow:sync` or git).
- **Fresh clone / new machine** (`git clone` brings `.agents/` **and** `.beads/issues.jsonl`):
  ```bash
  # from the repo root, after installing bd:
  bd init                   # create an empty local embedded-Dolt DB (no --remote)
  bd import                 # load issues from the tracked .beads/issues.jsonl
  bd stats                  # verify the issue history imported
  ```
  The binary Dolt store is regenerated locally; only the JSONL travels in git.
- Commits follow Conventional Commits; branches Conventional Branch; PR titles Conventional PR.
