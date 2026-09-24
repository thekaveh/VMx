# 11. Contributing & Releases

This page is the short routing layer for contributors. The operational source of
truth remains the repository docs.

## 11.1. Start With

- Contributing guide:
  [CONTRIBUTING.md](../../CONTRIBUTING.md)
- Spec index:
  [spec/README.md](../../spec/README.md)
- Compatibility matrix:
  [compatibility-matrix.md](../../compatibility-matrix.md)

## 11.2. Contribution Flow

- Open an issue for non-trivial work.
- Branch from `develop`, open the feature PR to `develop`, and run the relevant
  flavor checks locally.
- Promote `develop` to protected `main` only through a separate maintainer PR.
- Direct pushes to `develop` and `main` are blocked. Both PR stages require the
  always-present conformance, C#, Python, TypeScript, Swift, Rust, docs,
  examples, security, and spec-discipline aggregate checks against the latest
  target branch. Maintainer review is expected when another reviewer is
  available; the single-collaborator repository does not require self-approval.
- For behavior changes, start in `spec/` and follow the ADR discipline.
- Keep all supported flavors visible when a change affects shared behavior.

## 11.3. Validation Entry Points

The main local check families are:

- C#: restore, build, test, and `dotnet format`
- Python: `uv run pytest`, `ruff`, and `mypy --strict`
- TypeScript: `npm ci`, fixture sync, typecheck, lint, build, and test
- Swift: `swift build` and `swift test`
- Rust: `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, and
  `cargo test --locked`
- Repo-wide coverage and example-contract tools from `CONTRIBUTING.md`

Use the canonical command list in
[CONTRIBUTING.md](../../CONTRIBUTING.md)
instead of copying commands from this page into long-lived process docs.

For reproducible Python checks, set `UV_PYTHON` to the intended supported
version (3.10–3.14) before locked sync and subsequent uv commands. Installing
Python alone does not select it for an existing compatible environment. CI
selects the matrix version and logs the requested version, actual major/minor,
executable, and virtualenv prefix before checks. Later checks compare against
the captured executable. Isolated wheel, sdist, and tool environments keep
their own identities and must use the same requested version. The Ubuntu 3.10
cell deliberately seeds a 3.14 environment and verifies sync repairs it.

## 11.4. Spec Discipline

Two repo rules matter most:

- semantic changes under `spec/` require a matching ADR unless the change is in
  an exempt path
- new conformance IDs require matching stubs in every catalog-complete flavor

Those rules are enforced in CI and described in the contributing guide and
repository automation.

## 11.5. Release Shape

Flavor packages version independently and release from verified `main` commits
through `<lang>-vX.Y.Z` operational tags. C# uses that form for core and
package-specific `csharp-notifications-vX.Y.Z` and
`csharp-dependency-injection-vX.Y.Z` tags for its companions, so independent
versions cannot collide. The spec uses `spec-vX.Y.Z`; Swift also pairs its
operational tag with the semantic `vX.Y.Z` tag required by SwiftPM.
Registry-backed channels are protected by environment approval, OIDC,
pre-publish checks of the exact locally built artifact, public-artifact checks,
and fresh-consumer verification. The Python channel pins its isolated PEP 517
backend and installs/smokes the wheel from `dist/` before the irreversible PyPI
action, then repeats the consumer check from the public registry.

### 11.5.1. Release Checklist

Use this sequence for every flavor so the repository, site, and wiki carry the
same actionable procedure:

1. Start from a clean, freshly fetched `origin/main`; never release from
   `develop` or an unmerged feature branch.
1. Confirm the source/package version and minimum-spec declaration agree, and
   prove both the intended operational tag and public registry version are
   unused.
1. Run the flavor's complete release gate and build the exact package locally.
   Inspect that artifact, install it into a clean consumer, and retain the check
   evidence before creating a tag.
1. Create the immutable `<lang>-vX.Y.Z` tag from the verified `main` commit. For
   Swift, create the paired semantic `vX.Y.Z` tag from the same commit. For C#
   companion packages, use their package-specific tag prefixes.
1. Monitor the matching release workflow, approve its protected environment
   only after the pre-publish jobs identify the expected artifact, and do not
   bypass a failed gate.
1. Verify the exact version on the public registry and install it into a second
   fresh consumer. Confirm the GitHub release points to the tagged commit and
   contains the expected artifacts and notes.
1. If source, build, package-publication, or package behavior fails after tag
   creation, keep the tag immutable. Correct the source or workflow on `main`,
   bump the affected package to a new patch version, and publish through a new
   tag. For the React adapter only, a missing GitHub Release after successful
   registry, provenance, and fresh-consumer gates is metadata-only recovery;
   follow the [React-specific recovery runbook](#1153-recover-react-release-metadata).

### 11.5.2. Validate Python Release Tests

Once the dispatch-capable workflow is on the default branch, `develop`, run
`gh workflow run release.yml --ref develop` to validate only the five-version
Ubuntu Python test matrix. Dispatch has no publication inputs, and all other
release jobs require a tag push, including when dispatch targets an existing
release tag. This does not exercise the protected build/publish job; normal
Python CI separately checks wheel and extracted-sdist packaging. Real tag
pushes retain their main-ancestry and publication gates.

Rerun a successful revision to collect warm-cache evidence. The 3.10 cell must
report `cache-hit=true`, list both managed versions, and log the seeded 3.14
and selected 3.10 identities. A setup-uv package-cache hit is neither a restored
virtualenv nor necessarily a cached Python installation. Record the run URL
and revision; no historical interpreter selection is inferred. See
[CONTRIBUTING.md](../../CONTRIBUTING.md) for the full local procedure.

### 11.5.3. Recover React Release Metadata

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
