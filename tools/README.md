# tools/

Cross-cutting scripts that operate across `spec/` and `langs/`.

## 1. Current

- `check-conformance-coverage.py` — parses `spec/12-conformance.md` for the catalog
  of `XXX-NNN` conformance IDs and walks each active language's registered conformance
  test directory for matching tests. The exact directories are registered in the
  `_SCRAPERS` dictionary at the top of `tools/check-conformance-coverage.py`; running
  the tool prints the discovered paths per language. Reports gaps to stdout and exits
  non-zero if any language passed via `--require` has gaps. Used by the `conformance`
  CI workflow.

  ```bash
  # report-only
  python3 tools/check-conformance-coverage.py

  # CI mode — require all three flavors to be at 100% coverage (matches
  # .github/workflows/conformance.yml)
  python3 tools/check-conformance-coverage.py \
      --require csharp --require python --require typescript
  ```

  Unit tests live in `tools/tests/`. Run with:
  ```bash
  uv --project langs/python run pytest tools/tests/
  ```

<!-- Future tooling ideas (matrix generator, spec-to-docs renderer) are tracked as
GitHub issues rather than carried inline here, so this README stays a description
of what exists rather than what might exist someday. -->
