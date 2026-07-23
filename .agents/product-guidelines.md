# Product & Style Guidelines

## Tone of Voice

- Clear, concise, and technical. Documentation reads like good Litestar docs: practical and example-first.
- No hype. Describe what a battery does and when to use it, not how amazing it is.

## API Design Principles

- **First-party feel:** APIs should look and feel like they could live in Litestar itself.
- **Explicit over implicit:** No magic that surprises the caller. Prefer clear names and typed signatures.
- **Fully typed:** Every public surface is type-hinted; the package ships `py.typed`.
- **Composable:** Batteries are opt-in and independent; importing one should not force others.
- **Minimal dependencies:** Prefer the standard library. Any third-party dependency must be justified
  and documented in `tech-stack.md` before use.

## Documentation Requirements (Document-Driven Development)

Per the project's DDD approach: write docs first, then build to match.

1. Document the battery's purpose, public API, and usage examples.
2. Review the docs as the contract.
3. Implement to match the documented design.

## Constraints

- Public functions/classes require Google-style docstrings.
- Backwards compatibility matters once a battery is released; breaking changes must be documented.
