# VMx — Python flavor

The Python implementation of the VMx hierarchical MVVM framework, published as the `vmx` PyPI package.

- Supported Python versions: 3.10, 3.11, 3.12, 3.13
- See the language-neutral spec at [`/spec/`](../../spec) and the design doc at
  [`/docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md`](../../docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md).

## Status

**v1.0.0** — implements `spec-v1.0.0` end-to-end. 68/68 conformance tests pass.
Supports Python 3.10 through 3.13. `mypy --strict` clean.

See [`docs/getting-started/python.md`](../../docs/getting-started/python.md) for a tutorial.

## Build and test

```bash
uv sync --all-extras
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy --strict src/vmx
```
