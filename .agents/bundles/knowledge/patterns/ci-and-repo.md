---
type: Pattern
title: CI and Repository Patterns
description: CI that mirrors the local gate, reproducible installs, action pinning, and self-sufficient harness files.
tags: [ci, github-actions, repository]
---

# CI and Repository Patterns

- **CI mirrors local exactly:** `.github/workflows/ci.yml` runs the same five canonical commands as jobs lint / typecheck / test (matrix Python 3.10 & 3.14, `fail-fast: false`).
- **Reproducible installs:** every CI job runs `uv sync --frozen` against the committed `uv.lock`; regenerate with `uv lock` and commit whenever dependencies change.
- **Pin actions by commit SHA** with a version comment; Renovate updates them. setup-uv has no floating major tag.
- **Committed harness files must not depend on uncommitted context:** `AGENTS.md` stays self-sufficient so a fresh clone can build and verify without Flow artifacts.
- **Triage bot reviews (Codex, Copilot, CodeRabbit) on evidence:** verify each finding, fix valid ones with regression tests, and reply with reasoning on false positives (e.g. the msgspec mutable-default warning).
