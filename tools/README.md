# tools/

Cross-cutting scripts that operate across `spec/` and `langs/`.

Planned (Phase 1):

- `check-conformance-coverage.py` — enumerates `XXX-NNN` IDs in `spec/12-conformance.md`
  and verifies every active language flavor has a matching test. Used by
  `.github/workflows/conformance.yml`.
- `build-compatibility-matrix.py` — regenerates `compatibility-matrix.md`
  from spec/version files in each `langs/<lang>/`.
- `spec-to-docs.py` — renders `spec/` into `docs/concepts/` for the docs site.

This directory is intentionally empty in Phase 0.
