---
type: Log
title: Bundle Log
description: Dated history of completed flows and bundle changes. Current-state guidance lives in knowledge/.
tags: [log, history]
---

# Bundle Log

> Commit SHAs come from task close records. SHAs given with a PR number are on `main`; the rest are pre-squash branch commits that may only survive on their feature branch.

## 2026-10-09

- **setup:** Migrated the legacy flat `.agents/` layout and the Beads tracker (`.beads/issues.jsonl`, 36 records, all closed) to OKF v0.2 bundles. Completed-flow history below was synthesized from the archived specs, `learnings.md` files, and Beads close reasons; knowledge was resynthesized into `knowledge/`. Mapping: `.agents/migration-inventory.json`.

## 2026-10-08

- **idempotency-battery (follow-ups):** PR #12 review hardening (Beads `xup`): query-string fingerprinting and Redis claim retry (`6f2ef7b`); bounded request buffering, delivery-failure claim preservation, valid 204 replay headers (`8ee9f04`); complete-response-only caching (`456df83`); owner-token fencing with Lua compare-and-set (`502463b`); response pre-copy cap and 426 exclusion; cancellation shielding; empty-key rejection; `Content-Range` replay; trailer responses uncacheable; representation-aware fingerprint. 48 tests, 96.61% coverage. Merged as `474cd52` (#12).
- **idempotency-battery (post-merge fix):** delegate post-body `receive()` to the server so disconnect watchers see `http.disconnect` (Beads `knt`). 59 tests, 97.07% coverage. Merged as `36f0137` (#25).

## 2026-08-06

- **idempotency-battery (hardening, Beads epic `9ke`, 5 tasks):** after a prior-art survey (IETF draft-07, Stripe, 8 libraries), added scope/tenant isolation, opt-in `AtomicClaim`/`RedisAtomicClaim`, response header allow-list, streaming/oversized short-circuit, RFC 9457 errors + `require_key` + key validation (`7e39a42`). 32 tests, 98% coverage. Deferred: HMAC fingerprint, lease renewal, metrics, `no-store` opt-out.

## 2026-07-31

- **idempotency-battery (Beads epic `va8`, 4 tasks):** `IdempotencyPlugin` ASGI middleware deduping retried `POST`/`PATCH` by `Idempotency-Key` — replay, `409` in flight, `422` on fingerprint mismatch, `5xx` never cached; Litestar `Store` backing (Redis via `stores=`). Tasks: scaffold `e79a9e8`; TDD tests + middleware `cf3e7db`; README + gate `a787106`. PR #12 review: 2xx/4xx-only caching, length-delimited store key, `max_body_bytes`, `lock_ttl` caveat, disconnect bypass. 25 tests, 98% coverage.

## 2026-07-30

- **health-timeout (Beads feature `8lt`, 3 tasks + 2 review bugs):** opt-in `HealthCheck.timeout` running the check under `asyncio.wait_for`, deadline → `CheckResult` error → `503` (`65c0f83`). PR #8 review: `_guarded` wrapper disambiguates the deadline from a check's own `TimeoutError`; `wait_for` kept so caller cancellation never orphans the check. 12 tests, 100% coverage. Merged as `3891d2e` (#8).
- **docs (Beads `p33`):** README documents install + health battery incl. per-check timeout (`5f19232`, #10).
- **chore (Beads `m6n`):** MIT LICENSE; PEP 639 `license` + `license-files` (`f4dc239`, #11).

## 2026-07-23

- **project-foundation (Beads epic `52a`; chapters `axm` local-tooling, 4 tasks, and `1yk` ci-pipeline, 2 tasks):** ruff, strict mypy + pyright, pytest with 80% coverage gate, runtime `__version__`, smoke tests; GitHub Actions lint / typecheck / test matrix (3.10 & 3.14) mirroring the local gate; `uv sync --frozen`. Merged as `6edb155` (#1).
- **health-battery (Beads epic `2tg`, 5 tasks):** first battery — `HealthPlugin` (`InitPlugin`) with `GET /health` liveness and `GET /health/ready` readiness (sequential async checks, `200`/`503`, per-check results, `503` declared in OpenAPI); msgspec models; `litestar` + `msgspec` direct deps. Review fixes `652ee39`, `4d8a281`. 100% coverage. Merged as `6edb155` (#1).
