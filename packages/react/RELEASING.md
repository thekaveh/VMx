# Releasing `@thekaveh/vmx-react`

The adapter is independently versioned and uses `react-v<X.Y.Z>` tags. It is
published only from a verified commit on `main`, after the exact compatible
`@thekaveh/vmx` core range is publicly installable.

## 1. One-time bootstrap

1. Complete issue #57 and verify the core package from a fresh npm consumer.
2. Confirm ownership of the `@thekaveh` npm scope and availability of
   `@thekaveh/vmx-react`.
3. Create the protected `npm-react` GitHub environment, restricted to
   `react-v*` tags with required maintainer approval.
4. Add a short-lived granular `NPM_TOKEN` limited to the adapter for the first
   publication. Revoke it after configuring npm trusted publishing for
   `thekaveh/VMx`, `release.yml`, and environment `npm-react`.

Never create the bootstrap tag until the core package and owner authorization
are both verified.

## 2. Release procedure

1. Land release changes through develop and main. Update `package.json` and add
   a substantive matching changelog section.
2. Run the package, React 18/19, packed-consumer, showcase, security, and docs
   gates from a clean checkout.
3. Confirm `react-v<X.Y.Z>` and the npm version do not exist.
4. Tag the verified main commit and push the immutable tag.
5. Approve the protected environment and monitor publication, provenance,
   fresh React 18/19 consumers, and the GitHub Release.

If npm accepts a broken version, fix forward with a patch; never move or reuse
the tag/version. Publication remains a separate release operation from issue
#80's source integration.

## 3. Recover missing GitHub Release metadata

Use this procedure only when the exact npm version, provenance, and both fresh
React consumers have passed. A broken published package requires a new patch;
a missing GitHub Release alone is a metadata-only recovery.

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
  awk -v v="$version" -f tools/extract-react-release-notes.awk > "$notes"
test -s "$notes" && grep -q '[^[:space:]]' "$notes"
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
