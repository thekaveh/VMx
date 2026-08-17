# Release Please Unreleased-Section Repair Design

## Problem

Release Please correctly creates the Python version bump and release notes, but it
inserts the new linked release heading above the existing empty
`## [Unreleased]` section. VMx requires every current changelog to retain one canonical, empty
`## [Unreleased]` section as its first bracketed level-two heading. The generated
Python release PR therefore fails `tools/check-version-consistency.py`.

## Considered approaches

1. Repair each release PR manually. This unblocks one release but repeats a
   fragile human ritual forever.
1. Relax the changelog consistency rule for release PRs. This would allow merged
   `main` to lose the repository's required place for pending notes.
1. Post-process Release Please's generated branch. This preserves Release Please
   as the version and release-note authority while deterministically restoring
   the VMx-specific changelog invariant. This is the selected approach.

## Design

Add an idempotent Python tool that accepts a changelog path. If the changelog has
exactly one canonical `## [Unreleased]` heading in the required position, the
tool makes no change. If Release Please inserted its linked release heading above
an existing empty Unreleased section, the tool moves the empty section back to
the first bracketed position. If the heading is absent, it inserts an empty
canonical section immediately before the first bracketed release heading.
Ambiguous input—duplicates, a misplaced Unreleased section containing notes, or
no numbered release heading—fails without rewriting the file.

Give the Release Please action step an ID. When its documented `prs_created`
output is true, retain the trusted `main` checkout at the workspace root and
check out the mutable generated PR head into `release-pr/` with
`RELEASE_PLEASE_TOKEN`. Execute only the trusted root normalizer against the
nested changelog, then run scoped `git -C release-pr` commands to commit and push
only if it changed. The PAT-authored push triggers the normal protected-PR
checks. A release-created run has no updated PR, so the repair steps are skipped.

## Safety and verification

- Keep the repair limited to `langs/python/CHANGELOG.md`.
- Never execute mutable release-branch code with the PAT present; its persisted
  checkout credential remains confined to the nested checkout used for the
  authenticated push.
- Test missing, already-correct, duplicate, empty-misplaced, nonempty-misplaced,
  linked Release Please, and malformed inputs.
- Add workflow-contract assertions for the action output gate, PR-head checkout,
  PAT use, normalizer invocation, and conditional commit/push.
- Run focused tool tests, the full tools suite, version consistency, workflow pin
  validation, YAML/pre-commit checks, and `git diff --check` before integration.

## Release sequence

Merge the automation repair from its feature branch to `develop`, promote
`develop` to `main`, allow Release Please to refresh PR #298, wait for green CI,
then merge PR #298. The resulting `python-v3.23.1` tag runs the existing tested
OIDC publication pipeline and pauses at the protected `pypi-python` environment
for the maintainer's approval.
