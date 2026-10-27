# Releasing `@thekaveh/vmx-react`

The adapter is independently versioned and uses `react-v<X.Y.Z>` tags. It is
published only from a verified commit on `main`, after the exact compatible
`@thekaveh/vmx` core range is publicly installable.

Every release follows the shared
[release invariants](../../CONTRIBUTING.md#43-release-invariants): protected
environment, trusted publisher, annotated immutable tags, fix-forward patches,
and documentation updates. This runbook adds only the adapter steps.

## 1. Environment and trusted publisher

The protected `npm-react` environment is restricted to `react-v*` tags. The npm
trusted publisher is pending until a trusted publish succeeds. The first trusted
publish, tag `react-v0.1.2`, failed with `E404`. That error means npm found no
matching trusted publisher ([#653](https://github.com/thekaveh/VMx/issues/653)).
Do not push a new release tag until #653 records a successful trusted publish.
The publisher must use the shared fields with environment `npm-react` and
"Allow npm publish" ticked. The bootstrap procedure is in git history.

## 2. Release procedure

1. Land release changes through develop and main. Update `package.json` and add
   a substantive matching changelog section.
2. Run the package, React 18/19, packed-consumer, showcase, security, and docs
   gates from a clean checkout.
3. Confirm `react-v<X.Y.Z>` and the npm version do not exist.
4. Create the annotated `react-v<X.Y.Z>` tag on the verified main commit and
   push it.
5. Approve the protected environment and monitor publication, provenance,
   fresh React 18/19 consumers, and the GitHub Release.

If npm accepts a broken version, fix forward with a patch; never move or reuse
the tag/version.

## 3. Recover missing GitHub Release metadata

The release notes are the changelog body between the exact `## [X.Y.Z]`
heading and the next level-two heading. The helper
`tools/extract-release-notes.awk` compares the version literally.
Level-three headings stay in the body. The workflow fails on empty notes and
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
