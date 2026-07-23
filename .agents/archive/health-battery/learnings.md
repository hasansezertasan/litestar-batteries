## [2026-07-23] Code review (health-battery + project-foundation)

Two parallel reviewers (litestar-reviewer + general). No Critical. Applied fixes (commit 652ee39):

- **msgspec direct dependency** — public API exposes `msgspec.Struct` types; added `msgspec` to `dependencies` (was transitive via litestar).
- **503 in OpenAPI** — dynamic `Response(status_code=...)` isn't inferred; declared via `responses={503: ResponseSpec(HealthReport, ...)}`. Verified schema now lists 200 + 503.
- **Typed status** — `Status = Literal["ok","error"]`; schema renders a proper enum.
- **CI mypy checked src only** — config said `files=["src","tests"]`; changed CI + canonical command to `uv run mypy` (no path) so tests are type-checked too (they pass).
- **`uv sync --frozen`** in all CI jobs for reproducible installs against the committed lock.
- **Sequential checks** — documented the contract (didn't add `asyncio.gather`; would change error semantics — YAGNI).

Challenge-vetted rejections:
- `msgspec.field(default_factory=list)` — reviewer suggestion, but bare `list` trips pyright strict (`list[Unknown]`); the original `= []` is already per-instance-safe in msgspec, so kept it (with a clarifying comment).
- No manual controller-mount export (plugin-only is the intended contract); `except Exception` in readiness is correct (BaseException still propagates); lint/typecheck not pinning Python is correct by design.

## [2026-07-23] Automated bot reviews (Codex + Copilot) on PR #1

- **Codex — CLAUDE.md references local-only .agents/*** (valid P2): committed CLAUDE.md mandated reading git-ignored files a fresh clone lacks. Fixed (4d8a281): made CLAUDE.md self-authoritative; noted .agents/Beads are local-only.
- **Codex — `ruff check .# lint`** (valid P2): missing space before `#` → bash passed `.#`/`lint` as file args. Fixed (4d8a281) + refreshed the canonical command block.
- **Copilot — mutable `[]` default on HealthReport.checks** (REJECTED, false positive): it's a `msgspec.Struct`, not a dataclass; msgspec special-cases empty-literal defaults as per-instance factories (verified `is` → False on 0.21.1). Replied on the PR with reasoning.
- CodeRabbit hit its per-dev review rate limit; its main review did not run.

Lesson: committed harness files (CLAUDE.md) must not hard-depend on local-only Flow artifacts — keep them self-sufficient for fresh clones.
