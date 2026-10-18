---
type: Spec
flow_id: secure-headers-battery
title: Secure-headers battery
state: completed
plan_revision: 1
plan_commit: null
state_revision: 0
current_task: null
last_operation: null
operation_targets: []
last_verified_checkpoint: "9aff046: tox run green 3.10-3.14 + style + docs-doctest; correctness review a6f1f16 (fixed in 9aff046); quality review 9aff046: 0 Critical/Important, 3 Minor logged in learnings.md"
created_at: 2026-10-16T01:50:00Z
updated_at: 2026-10-16T01:50:00Z
description: Add SecureHeadersPlugin and SecureHeadersConfig, a helmet-style plugin that sets curated HTTP security response headers with safe defaults and per-field overrides (GitHub issue #14).
tags: [feature, security, headers, litestar]
parent_prd: null
research: [research/secure-headers.md]
---

# Flow: Secure-headers battery

**Flow ID:** `secure-headers-battery`
**Issue:** hasansezertasan/litestar-batteries#14 (PR body must contain `Closes #14`)

## Specification

### Code Analysis Summary

- `src/litestar_batteries/idempotency/{__init__,models,plugin,middleware}.py` - reference shape for a battery: dataclass `*Config` in `models.py`, `InitPlugin` with a **sync** `on_app_init` in `plugin.py`, public API in the subpackage `__init__` (`__all__`), re-exported from `src/litestar_batteries/__init__.py`.
- `src/litestar_batteries/health/` - first battery, same layout.
- `pyproject.toml:285-318` - import-linter contract: `exhaustive = true`, `layers = ["health | idempotency"]`. A new subpackage not listed fails `tox run -e style`.
- `tests/test_idempotency.py`, `tests/test_health.py` - tests use `litestar.testing.create_test_client(route_handlers=[...], plugins=[...])`.
- `docs/modules.rst` - per-battery `automodule` sections ("document each new battery here"); `README.md:66-285` - "Batteries" section with per-battery subsections and a `Configuration` table; README code blocks are doctested by the tox docs env.
- Litestar 2.24.0 is installed. `AppConfig.before_send: list[BeforeMessageSendHookHandler]`; `MutableScopeHeaders` exposes `setdefault`/`__setitem__`/`from_message`.
- No equivalent exists in Litestar or the community (research F1).

### Relevant Patterns

From `knowledge/patterns/battery-design.md`: battery = `InitPlugin` + dataclass config; plugin-only registration; **opt-in, backward-compatible config**; `Literal[...]` for enum-like strings; survey prior art first and record deferred items; verify external APIs before planning. From `testing.md`: `create_test_client`; every defect gets a regression test; assert strength (a default must be proven by a test that would catch a wrong default). From `architecture.md`: siblings must not import each other. Repo rules (`AGENTS.md`): absolute imports, strict typing, max cyclomatic complexity 5, 99% coverage gate, never edit `_version.py`.

### Decisions

Locked by the maintainer (2026-10-16):

- **D1 - HSTS on, HTTPS-only, 1 year.** Default `max-age=31536000`, emitted only when `scope["scheme"] == "https"` (the hook only sees HTTP response starts). `includeSubDomains` and `preload` are separate explicit opt-ins; `None` disables HSTS.
- **D2 - Non-breaking baseline CSP.** Default `frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'` (no `default-src`/`script-src`), so the OpenAPI UIs keep working with no path exemption. A full policy is supplied through config; a "strict" example goes in the README.
- **D3 - Handler wins.** Default `setdefault` semantics (a header already present on the response is left alone); `override=True` forces the battery's values.

Decided by the planner from the research (change via `revise` if disputed):

- **D4 - Mechanism: a `before_send` hook, not route middleware.** Route-level ASGI middleware misses router-level 404/405 (F4); `before_send` covers 200/404/405/500 (F5). The plugin appends its hook to `app_config.before_send` (preserving user hooks) and acts only on `http.response.start`; websocket and body messages pass through untouched.
- **D5 - `X-XSS-Protection` is never emitted** and has no config field (deprecated, F8).
- **D6 - Defaults** (each `None` disables the header; a `bool` field emits a fixed value):

  | Config field | Header | Default |
  |---|---|---|
  | `hsts_max_age: int \| None` | `Strict-Transport-Security` | `31536000` (HTTPS only) |
  | `hsts_include_subdomains: bool` | (HSTS directive) | `False` |
  | `hsts_preload: bool` | (HSTS directive) | `False` |
  | `content_type_options: bool` | `X-Content-Type-Options: nosniff` | `True` |
  | `frame_options: Literal["DENY","SAMEORIGIN"] \| None` | `X-Frame-Options` | `"DENY"` |
  | `content_security_policy: str \| None` | `Content-Security-Policy` | baseline (D2) |
  | `content_security_policy_report_only: str \| None` | `Content-Security-Policy-Report-Only` | `None` |
  | `referrer_policy: str \| None` | `Referrer-Policy` | `"strict-origin-when-cross-origin"` |
  | `permissions_policy: str \| None` | `Permissions-Policy` | `"camera=(), microphone=(), geolocation=()"` |
  | `cross_origin_opener_policy: str \| None` | `Cross-Origin-Opener-Policy` | `"same-origin"` |
  | `cross_origin_resource_policy: str \| None` | `Cross-Origin-Resource-Policy` | `None` (deviates from the research table: it blocks cross-origin embedding of an API's assets, so it is opt-in) |
  | `cross_origin_embedder_policy: str \| None` | `Cross-Origin-Embedder-Policy` | `None` |
  | `permitted_cross_domain_policies: str \| None` | `X-Permitted-Cross-Domain-Policies` | `"none"` |
  | `override: bool` | (precedence, D3) | `False` |

  Not managed (out of scope, recorded as deferred): `Cache-Control`, `Clear-Site-Data`, `X-DNS-Prefetch-Control`, `Origin-Agent-Cluster`, `X-Download-Options`, per-path rule sets, CSP nonces, trusted-proxy-aware HSTS scheme detection (documented: run the server with proxy headers so `scope["scheme"]` is correct).
- **D7 - Validation in `__post_init__`** raising `ValueError` (config errors surface at app construction): header values must not contain CR/LF (or be non-latin-1); `hsts_max_age >= 0`; `hsts_preload` requires `hsts_include_subdomains` and `hsts_max_age >= 31536000`; `hsts_include_subdomains`/`hsts_preload` set while `hsts_max_age is None` is an error.
- **D8 - Package layout:** `src/litestar_batteries/secure_headers/{__init__,models,hooks,plugin}.py`; public API is `SecureHeadersConfig` and `SecureHeadersPlugin`, re-exported from `litestar_batteries`. `hooks.py` is internal (`build_before_send(config)`).

### Requirements

**Functional**
- F-1 `SecureHeadersPlugin(config: SecureHeadersConfig | None = None)` registers the hook; defaults per D6.
- F-2 Every HTTP response (2xx, 4xx incl. router 404/405, 5xx) carries the configured headers; disabled (`None`/`False`) headers are absent.
- F-3 Precedence per D3; header names matched case-insensitively.
- F-4 HSTS only on `https` scheme (D1); directive string built as `max-age=N[; includeSubDomains][; preload]`.
- F-5 Websocket scopes and non-`http.response.start` messages are untouched; user-registered `before_send` hooks are preserved and still run.
- F-6 Invalid config is rejected per D7.
- F-7 The OpenAPI UI routes still render under the default config (no CSP breakage).

**Non-functional**
- NF-1 No new runtime dependency. NF-2 `from __future__ import annotations`, strict mypy/pyright, complexity <= 5 per function (table-driven header assembly, headers precomputed once at plugin init, not per request). NF-3 Coverage stays >= 99% (project gate). NF-4 `secure_headers` imports no sibling battery; added to the import-linter contract in the same commit that creates the package. NF-5 No behavior change for apps that do not register the plugin.

**API:** new public names `SecureHeadersConfig`, `SecureHeadersPlugin`. **DB:** none.

**Risks**
- R-1 `before_send` ordering vs user hooks: the plugin hook is appended last; with `override=False` earlier hooks win, with `override=True` the battery wins. Covered by task 1.3 tests.
- R-2 The default HSTS ships on; mitigated by HTTPS-only emission and README guidance on testing with a small `hsts_max_age` first.
- R-3 `litestar>=2` lower bound: tox only resolves the locked Litestar 2.24. Task 1.3 runs the tests once against `litestar==2.0.0` via `uv run --isolated --with` and records the result; if it fails, raise the lower bound in `pyproject.toml` as part of that task.
- R-4 Redoc `blob:`/font needs are unverified; irrelevant under the baseline CSP (D2) but would matter if a user adopts a strict CSP; the README states the OpenAPI UIs need a relaxed policy.

### Requirement trace

| Req | Task(s) |
|---|---|
| F-1 | 1.1 (config/defaults), 1.3 (plugin) |
| F-2, F-7 | 1.3 |
| F-3, F-4, F-5 (hook level) | 1.2 |
| F-5 (user hooks preserved), R-1 | 1.3 |
| F-6, NF-4 | 1.1 |
| NF-2/NF-3 | 1.1-1.3 (every task runs `ruff`/`mypy`/focused coverage) |
| Docs (README + Sphinx API reference) | 2.1 |

## Implementation Plan

### Phase 1: Battery implementation

- [x] 1.1 Add `SecureHeadersConfig`, package scaffold and import-linter entry (`behavior_tdd`) (daa6ae33241c1f297f834da627e6f1b02e0c5a62)
- [x] 1.2 Add the `before_send` hook with precedence, HSTS and message filtering (`behavior_tdd`) (c63ff67)
- [x] 1.3 Add `SecureHeadersPlugin`, public exports and app-level integration tests (`behavior_tdd`) (893a394)

**Phase 1 checkpoint:** `uv run --locked pytest tests/test_secure_headers.py -v`, `uv run --locked tox run -e style` green; recorded via a `checkpoint` operation before Phase 2.

### Phase 2: Documentation

- [x] 2.1 Document the battery in `README.md` (`documentation_validation`) (cca7788)

**Final gate (before `flow-finish`):** `uv run --locked tox run` green on the full matrix with the 99% coverage gate; manually run a demo app and `curl -sI` a 200, a 404 and the `/schema` page to eyeball the headers; open the PR with branch `feat/secure-headers-battery`, title `feat: add secure-headers battery`, body `Closes #14`.

## Continuity Snapshot

- Lifecycle: completed on branch feat/secure-headers-battery (final functional commit 9aff046); all tasks closed. Current task: none. Claimant: none. Last verified checkpoint: none.
- Decisions: D1-D8 above. Plan revision 1; state revision 0.
- Discoveries: Litestar 2.24 route-level middleware misses router 404/405 (research F4); `before_send` does not.
- Blockers: none. Next exact step: archive (`flow-archive`) and/or open the PR (needs user approval).
- Rule/knowledge paths: `AGENTS.md`, `.agents/bundles/knowledge/patterns/battery-design.md`, `.agents/bundles/knowledge/patterns/testing.md`, `.agents/bundles/knowledge/workflow.md`.
