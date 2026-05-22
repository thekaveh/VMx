# tools/

Cross-cutting scripts that operate across `spec/` and `langs/`.

## Current

- `check-conformance-coverage.py` — parses `spec/12-conformance.md` for the catalog
  of `XXX-NNN` conformance IDs and walks each active language's registered conformance
  test directory (`langs/python/tests/conformance/` for Python,
  `langs/csharp/tests/VMx.Conformance.Tests/` for C#) for matching tests. Reports
  gaps to stdout and exits non-zero if any language passed via `--require` has gaps.
  Used by the `conformance` CI workflow.

  ```bash
  # report-only
  python3 tools/check-conformance-coverage.py

  # CI mode — require python and csharp to be at 100% coverage
  python3 tools/check-conformance-coverage.py --require python --require csharp
  ```

  Unit tests live in `tools/tests/`. Run with:
  ```bash
  uv --project langs/python run pytest tools/tests/
  ```

## Planned

- `build-compatibility-matrix.py` — regenerates `compatibility-matrix.md` from the
  spec version (`spec/VERSION`) and each language's declared `MinSpecVersion`. To
  be added when the first language flavor releases.
- `spec-to-docs.py` — renders `spec/*.md` into `docs/concepts/` for the docs site.
  To be added when the docs site is wired up (Phase 2k/3j).
