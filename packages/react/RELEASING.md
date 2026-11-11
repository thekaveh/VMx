# Releasing `@thekaveh/vmx-react`

The adapter is independently versioned and uses `react-v<X.Y.Z>` tags. It is
published only from a verified commit on `main`. At least one published
`@thekaveh/vmx` version must satisfy the adapter's `@thekaveh/vmx` peer range.

Every release follows the shared
[release invariants](../../CONTRIBUTING.md#43-release-invariants): protected
environment, trusted publisher, annotated immutable tags, fix-forward patches,
and documentation updates. This runbook adds only the adapter steps.

## 1. Environment and trusted publisher

The protected `npm-react` environment is restricted to `react-v*` tags. The npm
trusted publisher is pending until a trusted publish succeeds. Register it with
the shared fields, environment `npm-react`, and "Allow npm publish" ticked. The
bootstrap procedure is in git history at [commit `0c88386e`, §1](https://github.com/thekaveh/VMx/blob/0c88386eb3fffbe1d0620178bfd391745bd5db4e/packages/react/RELEASING.md#L7-L27).

The first trusted publish, tag `react-v0.1.2`, failed with `E404`. That error
means npm found no matching trusted publisher
([#653](https://github.com/thekaveh/VMx/issues/653)). Nothing was published
under 0.1.2.

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
   (`CONTRIBUTING.md` §4.3). The same PR updates the npm status in
   `packages/react/README.md` §1, because that README becomes the npm page.
2. Run the package, React 18/19, packed-consumer, showcase, security, and docs
   gates from a clean checkout.
3. Confirm `react-v<X.Y.Z>` and the npm version do not exist.
4. Create the annotated `react-v<X.Y.Z>` tag on the verified main commit and
   push it.
5. Approve the protected environment and monitor publication, provenance,
   fresh React 18/19 consumers, and the GitHub Release.

If npm accepts a broken version, fix forward with a patch; never move or reuse
the tag/version.

## 4. Release 0.1.3 after the failed 0.1.2

The `react-v0.1.2` tag is immutable, so the fixes it carried ship as 0.1.3. A
rerun of the failed 0.1.2 job cannot publish: it uses the tag's own
`release.yml`, whose full `npm audit` now fails on dev-only advisories. Leave
`react-v0.1.2` where it is, and do not rerun its workflow.

1. On npmjs.com, register the trusted publisher for `@thekaveh/vmx-react` as
   section 1 describes.
2. Promote `develop` to `main` with the 0.1.3 version and changelog section,
   after a release-prep PR dates the 0.1.3 heading as section 3 step 1
   describes.
3. On that main commit, run
   `python3 tools/check-version-consistency.py --release-tag react-v0.1.3`.
4. Follow section 3 from step 3 with tag `react-v0.1.3`.
5. After npm serves 0.1.3, record it in the compatibility matrix and docs
   ([#1039](https://github.com/thekaveh/VMx/issues/1039)).

## 5. Recover missing GitHub Release metadata

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
remove the temporary notes file.

Before recovery, read the old run's evidence and independently confirm the
immutable remote tag SHA, its ancestry from `main`, the package version at that
tag, the exact public npm version, its provenance, and the successful fresh
React 18 and React 19 consumer checks. These checks establish publication
facts; the extraction commands below do not. npm forbids reusing a published
package name and version, even after unpublishing; see the
[npm publish documentation](https://docs.npmjs.com/cli/v11/commands/npm-publish/).
Do not republish, move or recreate the tag, or reuse a version. Do not rerun
the historical workflow: a GitHub Actions rerun retains the original SHA and
ref, so it also retains the old extraction code. See GitHub's
[rerun documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs)
and [workflow documentation](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflows).

From a current, verified `main` checkout that contains the fixed helper, use
the changelog bytes from the original immutable tag. Substitute the actual
already-published version; never run this procedure for a package that has not
passed the checks above.

```bash
set -euo pipefail
version=0.1.0 # Replace with the version whose npm upload already succeeded.
tag="react-v${version}"
git fetch --no-tags origin "refs/tags/${tag}:refs/tags/${tag}"
tag_sha="$(git rev-parse "${tag}^{commit}")"
remote_tag_ref="$(git ls-remote --exit-code origin "refs/tags/${tag}" | awk '{print $1}')"
test "$remote_tag_ref" = "$(git rev-parse "$tag")"
git fetch --no-tags origin main:refs/remotes/origin/main
git merge-base --is-ancestor "$tag_sha" origin/main
notes="$(mktemp)"
git show "${tag_sha}:packages/react/CHANGELOG.md" |
  awk -v v="$version" -f tools/extract-release-notes.awk > "$notes"
test -s "$notes" && grep -q '[^[:space:]]' "$notes" || {
  echo "No adapter release notes." >&2
  exit 1
}
cat "$notes"
```

The fetch and `ls-remote` equality confirm the remote tag ref, and
`^{commit}` peels an annotated tag to its original commit. Any failed fetch or
remote query stops this script; do not infer a confirmed tag from a failure.
Inspect the rendered notes before continuing. Check whether a GitHub Release
already exists, and distinguish confirmed absence from an authentication or
network failure. If absent, create only release metadata:

```bash
gh release create "$tag" --verify-tag --target "$tag_sha" \
  --title "React adapter v${version} (npm)" --notes-file "$notes"
```

If it exists, verify its tag and update only its title and notes:

```bash
gh release edit "$tag" --title "React adapter v${version} (npm)" --notes-file "$notes"
```

Verify the release URL, tag SHA, and notes; retain the recovery evidence and
remove the temporary notes file. This changes GitHub Release metadata only.
