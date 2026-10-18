# Releasing the `@thekaveh/vmx` TypeScript package

This runbook documents the tag-driven npm release channel. A
`typescript-v<X.Y.Z>` tag on `main` starts `.github/workflows/release.yml`.
The workflow publishes only after the package and tag versions match and every
release gate passes.

Every release follows the shared
[release invariants](../../CONTRIBUTING.md#43-release-invariants): protected
environment, trusted publisher, annotated immutable tags, fix-forward patches,
and documentation updates. This runbook adds only the TypeScript steps.

## 1. One-time owner setup

### 1.1 Protected GitHub environment

Create the `npm-typescript` environment as the release invariants describe.
Restrict its deployment refs to `typescript-v*` tags.

### 1.2 npm trusted publishing

The npm trusted publisher is configured; the bootstrap procedure is in git
history. It uses the shared trusted-publisher fields with provider GitHub
Actions and environment `npm-typescript`. Its permission must be publish
("Allow npm publish"); without it the publisher may only stage, and the
workflow's public-install checks time out.

The workflow uses OIDC when the environment has no `NPM_TOKEN` secret.
Trusted publishing requires Node.js 22.14 or newer and npm CLI 11.5.1 or newer;
the publish job pins Node 24 and npm 11.18.0. npm automatically attaches
provenance for an eligible GitHub-hosted trusted-publishing run.

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
   git tag -a "typescript-v${version}" -m "VMx TypeScript ${version}" origin/main
   git push origin "typescript-v${version}"
   ```

6. Approve the `npm-typescript` environment deployment and watch the Release
   workflow.

### 2.1 Release gates

Before publishing, CI verifies main ancestry and exact tag/package version,
then runs fixture sync, both typechecks, lint, build, tests, audit, a strict
package-content allowlist, and a packed local consumer smoke test. The publish
job uses Node 24 and npm 11.18.0 without an npm dependency cache.

After npm accepts the package, separate Node 20.5.0, 22, 24, and 26 jobs poll for
and install the exact public version in clean consumers. They test ESM imports,
CommonJS `require`, NodeNext declarations, and the root, `notifications`,
`conformance`, `testing`, and `devtools` exports. They also require npm provenance metadata. Only after
those checks pass does CI create the TypeScript GitHub Release from the matching
changelog section.

### 2.2 Pre-releases

The workflow publishes to npm's default `latest` dist-tag, so it is
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

Apply the immutability invariant: land the fix on `main`, bump to a new patch
version, and create a new tag.

### 4.2 Authentication or trusted-publisher failure

Confirm that the environment approval completed and that the trusted publisher
matches `thekaveh/VMx`, `release.yml`, and `npm-typescript` exactly. Do not add a
long-lived token as a shortcut.

### 4.3 Publish succeeded but verification failed

npm versions are immutable. Diagnose the public artifact, fix forward, and
publish a new patch version. If the accepted version is unsafe or unusable,
deprecate it with a replacement message:

```bash
npm deprecate @thekaveh/vmx@X.Y.Z "broken release; use A.B.C"
```

Unpublish only when npm policy and a security incident require it; document the
decision publicly. Never silently replace or retag an accepted version.

## 5. Compatibility

TypeScript uses `typescript-v<X.Y.Z>`. The package's `__minSpecVersion__`
declares its minimum compatible VMx specification. After public verification,
update the documentation as the release invariants describe before completing
the release ticket.
