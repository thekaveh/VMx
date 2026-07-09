# Specification & Conformance

The VMx behavior contract starts in `spec/`, not in any single language
implementation.

## Source Of Truth

- Spec index:
  [spec/README.md](https://github.com/thekaveh/VMx/blob/main/spec/README.md)
- Current spec version:
  [spec/VERSION](https://github.com/thekaveh/VMx/blob/main/spec/VERSION)
- Compatibility matrix:
  [compatibility-matrix.md](https://github.com/thekaveh/VMx/blob/main/compatibility-matrix.md)

## What Lives In The Spec

- 23 numbered chapters from `00-overview.md` through `22-discriminator-vm.md`
- ADRs describing behavior and design decisions
- shared JSON fixtures consumed by the language flavors
- the cross-language conformance catalog in `spec/12-conformance.md`

## Conformance Model

The current catalog contains:

- 281 library IDs implemented by all five full-parity source flavors
- 5 `THEME-00x` scenario IDs exercised by the flagship example apps
- 286 total IDs in the published catalog

The source overview is here:
[spec/12-conformance.md](https://github.com/thekaveh/VMx/blob/main/spec/12-conformance.md).

## How The Repo Enforces It

- Each language flavor carries a conformance suite under its own tree.
- `tools/check-conformance-coverage.py` enforces full library coverage across
  C#, Python, TypeScript, Swift, and Rust.
- The examples workflows enforce the separate flagship scenario contract.

## Practical Reading Path

1. Read `spec/README.md` for chapter ownership and release history.
1. Read the primitive pages on this site for a faster conceptual map.
1. Use the flavor README when you need package details or host-specific
   examples.
1. Use the parity matrix and conformance catalog when you need proof rather than
   overview.
