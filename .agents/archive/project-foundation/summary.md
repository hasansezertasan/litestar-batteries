# Archive Summary: project-foundation

**Archived:** 2026-07-23
**Status:** Complete (merged in PR #1, squash commit 6edb155)
**Beads epic:** litestar-batteries-52a (closed)

Bootstrapped the dev toolchain and CI. Two chapters:
- local-tooling (axm): ruff, mypy+pyright (strict), pytest + 80% coverage gate, package __version__, smoke tests.
- ci-pipeline (1yk): GitHub Actions (lint / typecheck / test matrix 3.10 & 3.14) mirroring the local gate.

**Elevated patterns:** canonical verify command; strict-typing conventions (+ tests-scoped pyright override); hard coverage gate; CI mirrors local; setup-uv full-version pin; uv sync --frozen. See knowledge/conventions.md.
