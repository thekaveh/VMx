# Releasing `@thekaveh/vmx-react`

The adapter is independently versioned and uses `react-v<X.Y.Z>` tags. It is
published only from a verified commit on `main`. At least one published
`@thekaveh/vmx` version must satisfy the adapter's `@thekaveh/vmx` peer range.

Every release follows the shared
[release invariants](../../CONTRIBUTING.md#43-release-invariants): protected
environment, trusted publisher, annotated immutable tags, fix-forward patches,
and documentation updates. This runbook adds only the adapter steps.

## 1. Environment and trusted publisher

The protected `npm-react` environment is restricted to `react-v*` tags.
Register the npm trusted publisher with the shared fields, environment
`npm-react`, and "Allow npm publish" ticked. The bootstrap procedure is in git
history at [commit `0c88386e`, §1](https://github.com/thekaveh/VMx/blob/0c88386eb3fffbe1d0620178bfd391745bd5db4e/packages/react/RELEASING.md#L7-L27).

Until a trusted publish succeeds, confirm the trusted publisher on npmjs.com
before each tag. Without a matching publisher, npm rejects the publish with
`E404` ([#653](https://github.com/thekaveh/VMx/issues/653)), and nothing is
published under that tag. The
[compatibility matrix](../../compatibility-matrix.md) records the published
adapter versions.

## 2. Release gates

The `react-build` job of `release.yml` checks these items without
`id-token: write` or the publishing environment, then packs and uploads the
release tarball:

- The tag commit is on `main`, and the tag version equals `package.json`.
- A published `@thekaveh/vmx` satisfies the adapter's `@thekaveh/vmx` peer
  range. The job does not require the `langs/typescript` source version on npm.
- `npm audit --omit=dev --audit-level=low` passes. Dev-only advisories cannot
  reach consumers. The full lockfile, and the React 18 lockfile in
  `packages/react-18-deps`, are still audited on every pull request by
  `typescript.yml` and every week by `security-audit.yml`.
- Type-check, lint, tests, build, the package check, and packed React 18.3.1
  and 19.2.8 consumers pass.

The `react-publish` job in `npm-react` installs only the pinned npm CLI, checks
the tarball's name and version against the tag, and publishes that tarball.

## 3. Release procedure

1. Land release changes through develop and main. Update `package.json` and add
   a substantive matching changelog section. Immediately before the tag, a
   release-prep PR replaces `unreleased source version` in the `## [X.Y.Z]`
   heading with the release date, so the heading date equals the tag date
   (`CONTRIBUTING.md` §4.3).
2. Run the package, React 18/19, packed-consumer, showcase, security, and docs
   gates from a clean checkout.
3. Confirm `react-v<X.Y.Z>` and the npm version do not exist. On the verified
   main commit, run
   `python3 tools/check-version-consistency.py --release-tag react-v<X.Y.Z>`.
4. Create the annotated `react-v<X.Y.Z>` tag on the verified main commit and
   push it.
5. Approve the protected environment and monitor publication, provenance,
   fresh React 18/19 consumers, and the GitHub Release.

If npm accepts a broken version, fix forward with a patch; never move or reuse
the tag/version.

If a release fails before npm accepts the package, the tag still stays
immutable. Do not rerun that tag's workflow: a rerun uses the `release.yml` of
the tag commit, so it cannot pick up a fix. Ship the fix as the next patch
version with a new tag.

## 4. Recover missing GitHub Release metadata

The release notes are the changelog body between the exact `## [X.Y.Z]`
heading and the next level-two heading. The helper
`tools/extract-release-notes.awk` compares the version literally.
Level-three headings stay in the body. The helper ends a section at every
column-0 `##` line, so the version check rejects such a line inside a code
block or an HTML block. The workflow fails on empty notes and
prints the extracted notes for review.

Use this procedure only when the exact npm version, provenance, and both fresh
React consumers have passed. A broken published package requires a new patch;
a missing GitHub Release alone is metadata-only recovery. Preserve the
immutable tag and published version; do not republish, move or recreate the
tag, reuse the version, or rerun the historical workflow. First verify the
immutable tag, public package, provenance, and fresh React 18/19 consumers.
Then extract and inspect the tagged changelog with the current helper. Confirm
whether a GitHub Release is absent rather than blocked by authentication or the
network; create or edit only its metadata, then verify its notes and tag and
remove the temporary notes file. The canonical [React metadata recovery
procedure](../../docs/content/contributing-releases.md#1153-recover-react-release-metadata)
contains the complete commands.
