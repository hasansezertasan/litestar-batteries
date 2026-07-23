# Product Definition

<!-- truth: start -->
**litestar-batteries** is a "batteries-included" utility collection for [Litestar](https://litestar.dev)
applications: a package of reusable extensions, plugins, and helpers that reduce the boilerplate
teams write repeatedly when building production Litestar services.

- **Problem it solves:** Common Litestar needs (wiring, configuration, cross-cutting utilities) are
  re-implemented from scratch on every project. litestar-batteries packages battle-tested,
  first-party-flavored solutions so teams start further ahead.
- **Who it's for:** Python developers building applications and services on Litestar who want
  opinionated, well-tested building blocks instead of copy-pasted glue code.
- **Key differentiator:** Follows first-party Litestar patterns and idioms closely, is fully typed
  (`py.typed`), and favors the standard library plus deliberate, documented dependencies.
<!-- truth: end -->

## Scope

The exact set of "batteries" is defined incrementally through Flow specs. Each addition must:

- Follow first-party Litestar patterns (see `.agents/code-styleguides/litestar.md`).
- Ship with type hints and tests.
- Document its rationale before implementation (Document-Driven Development).

## Non-Goals

- Not a starter template or project scaffold.
- Not a fork or replacement of Litestar itself — it composes with Litestar, it does not replace it.
