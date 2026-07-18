# Releasing the `@thekaveh/vmx` TypeScript package

This runbook documents the tag-driven npm release channel. A
`typescript-v<X.Y.Z>` tag on `main` starts `.github/workflows/release.yml`.
The workflow publishes only after the package and tag versions match and every
release gate passes.

## 1. One-time owner setup

### 1.1 Protected GitHub environment

Create the `npm-typescript` environment in the `thekaveh/VMx` repository:

- restrict deployment refs to `typescript-v*` tags;
- require a maintainer approval; and
- do not permit administrators to bypass the protection.

The release job has `id-token: write`. Keep credentials on this environment,
not as repository-wide secrets.

### 1.2 First publication bootstrap

npm trusted publishing can be configured only after the package exists. The
first publication therefore needs an authenticated owner of the `@thekaveh`
scope and a narrowly scoped, short-lived granular access token:

1. Confirm that `@thekaveh/vmx` is available and that the authenticated account
   may create packages in the `@thekaveh` scope.
2. Create a granular token with publish access limited to `@thekaveh/vmx`.
3. Add it temporarily to the `npm-typescript` environment as `NPM_TOKEN`.
4. Approve and run the first immutable release. The token is mapped to
   `NODE_AUTH_TOKEN` only for the bootstrap publish step, which uses
   `npm publish --access public --provenance`.
5. Do not reuse a version after npm has accepted it. If verification fails
   after publication, fix the cause and release a new patch version.

Never create the first tag until scope ownership, the intended version, and the
protected environment are confirmed.

### 1.3 Switch to npm trusted publishing

After the first package is visible on npm, configure a trusted publisher in the
package settings with these exact values:

- provider: GitHub Actions;
- organization or user: `thekaveh`;
- repository: `VMx`;
- workflow filename: `release.yml`;
- environment: `npm-typescript`;
- permission: publish.

Then delete the `NPM_TOKEN` environment secret and revoke the bootstrap token.
The workflow detects the absent secret and uses OIDC. Trusted publishing
requires Node.js 22.14 or newer and npm CLI 11.5.1 or newer; the publish job pins
Node 24 and npm 11.5.1. npm automatically attaches provenance for an eligible
GitHub-hosted trusted-publishing run.

## 2. Cutting a release

1. Land the release changes on `main` through the repository's develop-to-main
   PR flow.
2. Confirm `langs/typescript/package.json` has the intended version and update
   `__minSpecVersion__` in `langs/typescript/src/version.ts` when required.
3. Add a matching `## [X.Y.Z] — YYYY-MM-DD` entry to
   `langs/typescript/CHANGELOG.md`.
4. From a clean checkout of current `origin/main`, verify the version and that
   neither the tag nor npm version exists:

   ```bash
   version=$(node -p "require('./langs/typescript/package.json').version")
   git ls-remote --exit-code --tags origin "refs/tags/typescript-v${version}" || true
   npm view "@thekaveh/vmx@${version}" version || true
   ```

5. Create the immutable tag on the verified main commit and push it:

   ```bash
   git tag "typescript-v${version}" origin/main
   git push origin "typescript-v${version}"
   ```

6. Approve the `npm-typescript` environment deployment and watch the Release
   workflow. Do not move, delete, or recreate a published release tag.

### 2.1 Release gates

Before publishing, CI verifies main ancestry and exact tag/package version,
then runs fixture sync, both typechecks, lint, build, tests, audit, a strict
package-content allowlist, and a packed local consumer smoke test. The publish
job uses Node 24 and npm 11.5.1 without an npm dependency cache.

After npm accepts the package, separate Node 20, 22, 24, and 26 jobs poll for
and install the exact public version in clean consumers. They test ESM imports,
CommonJS `require`, NodeNext declarations, and the root, `notifications`, and
`conformance` exports. They also require npm provenance metadata. Only after
those checks pass does CI create the TypeScript GitHub Release from the matching
changelog section.

### 2.2 Pre-releases

The workflow currently publishes to npm's default `latest` dist-tag, so it is
for stable releases only. Before cutting an alpha, beta, or release candidate,
change and test the workflow to pass an explicit non-latest dist-tag such as
`--tag next`; do not use a pre-release version with the stable workflow.

## 3. Independent verification

Use the repository smoke tool to repeat the same public-consumer checks:

```bash
python3 tools/smoke-npm-consumer.py --version X.Y.Z --poll-timeout 600
npm view @thekaveh/vmx@X.Y.Z dist.attestations --json
gh release view typescript-vX.Y.Z --repo thekaveh/VMx
```

Also verify the npm page, GitHub Release, generated documentation site, and wiki
from a fresh network request before changing the issue or roadmap item to Done.

## 4. Failure and recovery

### 4.1 Failure before publish

Fix the cause through the normal PR flow. If npm has not accepted the version,
delete the unpublished tag, land the fix on `main`, and create a new tag. Never
move a tag after a GitHub Release or npm version exists.

### 4.2 Authentication or trusted-publisher failure

Confirm that the environment approval completed and that the trusted publisher
matches `thekaveh/VMx`, `release.yml`, and `npm-typescript` exactly. Do not add a
long-lived token as a shortcut. During the one-time bootstrap only, replace an
expired granular token with another narrowly scoped, short-lived token.

### 4.3 Publish succeeded but verification failed

npm versions are immutable. Diagnose the public artifact, fix forward, and
publish a new patch version. If the accepted version is unsafe or unusable,
deprecate it with a replacement message:

```bash
npm deprecate @thekaveh/vmx@X.Y.Z "broken release; use A.B.C"
```

Unpublish only when npm policy and a security incident require it; document the
decision publicly. Never silently replace or retag an accepted version.

## 5. Compatibility and multi-flavor tags

TypeScript uses `typescript-v<X.Y.Z>`. Other flavors use independent tag
prefixes, so one flavor's tag does not publish another flavor. The package's
`__minSpecVersion__` declares its minimum compatible VMx specification. A spec
major bump requires a corresponding flavor major bump under `README.md` §6.1.

After public verification, update the canonical in-repository documentation,
regenerate the MkDocs `.io` site and GitHub wiki, and merge those publication
claims through develop and main before completing the release ticket.
