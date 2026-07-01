# Releasing the `@thekaveh/vmx` TypeScript package

This runbook documents how `@thekaveh/vmx` is published to npm.

The release pipeline is **manual tag-driven**: push a `typescript-v<X.Y.Z>`
tag on `main` and `.github/workflows/release.yml` handles the rest. There
is no automated version-bump PR (release-please is not yet wired for the
TypeScript component — a follow-up when adopting it, see
`langs/python/RELEASING.md` §2.2 for the tag-ordering gotcha).

## 1. Prerequisites (one-time, done by the package owner)

### 1.1 npm access token

- An npm account at <https://www.npmjs.com/signup> with 2FA enabled.
- Create a **Granular Access Token** scoped to the `@thekaveh/vmx` package
  with "Read and write" permission.
- In the repo's Settings → Secrets and variables → Actions, add the secret
  as `NPM_TOKEN`.

> **Token plus provenance.** The workflow authenticates with `NPM_TOKEN` and
> publishes with `npm publish --provenance`; the job has `id-token: write` so npm
> can attach provenance attestations. This is not npm Trusted Publishing yet:
> keep the token secret configured until the workflow is migrated to fully
> tokenless trusted publishing.

### 1.2 Pre-publish metadata validation

Every URL in `langs/typescript/package.json` (`homepage`, `bugs.url`,
`repository.url`) is rendered as a clickable link on the npm package page.
A 404 there is visible to every consumer. Before tagging, verify:

```bash
node -e "
const p = JSON.parse(require('fs').readFileSync('langs/typescript/package.json'));
const urls = [p.homepage, p.bugs?.url].filter(Boolean);
console.log(urls.join('\n'));
"
```

Check each URL is reachable before pushing the tag.

## 2. Cutting a release

### 2.1 Routine release (manual)

1. Land all intended changes on `main`.
2. Update the version in `langs/typescript/package.json` (e.g. `"version": "2.6.1"`).
3. Update `__minSpecVersion__` in `langs/typescript/src/version.ts` if the
   spec version also bumped (the release pipeline does not auto-bump it).
4. Add a `## [X.Y.Z] — YYYY-MM-DD` section to `langs/typescript/CHANGELOG.md`.
5. Commit and push directly to `main` (or via a PR).
6. Tag and push:

   ```bash
   git checkout main
   git pull --ff-only origin main
   node -e "console.log(require('./langs/typescript/package.json').version)"  # confirm version
   git tag typescript-v2.6.1
   git push origin typescript-v2.6.1
   ```

7. Watch <https://github.com/thekaveh/VMx/actions?query=workflow%3Arelease> —
   the publish pipeline fires on the tag.
8. The workflow verifies the tag commit is reachable from `origin/main` before
   it builds. If `NPM_TOKEN` is missing, the job fails before publish rather
   than green-skipping the release.

### 2.2 What the pipeline does

The `typescript` job in `release.yml` runs only when the tag starts with
`typescript-v`. It:

1. Checks out the repository and verifies the tag commit is reachable from
   `origin/main`.
2. Sets up Node 20 and restores `npm ci` from the lockfile.
3. Runs `npm run build` (compiles TypeScript, emits dual ESM + CJS via tsup;
   also runs `npm run sync-fixtures` via the `prebuild` hook to copy
   `spec/fixtures/*.json` into `src/fixtures/`).
4. Runs `npm test` (vitest).
5. Runs `npm audit --package-lock-only --audit-level=low`.
6. Fails if `NPM_TOKEN` is absent.
7. Runs `npm publish --access public --provenance`.

There is no separate verify-published or release-notes job for TypeScript
yet; add them alongside adoption of release-please.

### 2.3 Pre-release (`alpha`, `beta`, `rc`)

Use npm pre-release segments in `package.json`:

- `"version": "2.7.0-alpha.1"` → `npm publish` will tag it `next` by
  default; `npm install @thekaveh/vmx` (no version pin) won't pick it up.
  Pin with `npm install @thekaveh/vmx@2.7.0-alpha.1` or
  `npm install @thekaveh/vmx@next`.

## 3. Verifying a release

```bash
# npm page renders:
npm view @thekaveh/vmx version

# Install in a fresh project:
mkdir /tmp/vmx-ts-verify && cd /tmp/vmx-ts-verify
npm init -y
npm install @thekaveh/vmx@2.6.0
node -e "const vmx = require('@thekaveh/vmx'); console.log('ok', vmx.__minSpecVersion__)"
```

## 4. Failure modes

### 4.1 `npm test` failed

The publish step is skipped if tests fail (they run before `npm publish` in
the same job). Fix the test on `main`, cut a new tag with a bumped patch
version.

### 4.2 `NPM_TOKEN` not set / expired

The job fails before publish when the secret is absent or expired. Regenerate
the token on npm, update the `NPM_TOKEN` Actions secret, and re-run the failed
workflow. If the tag itself was wrong, delete and recreate it on `main`:

```bash
git push origin --delete typescript-v2.6.1
git tag -d typescript-v2.6.1
git tag typescript-v2.6.1
git push origin typescript-v2.6.1
```

### 4.3 Publish succeeded but the release is broken

npm allows `npm deprecate` but not deletion. Deprecate the bad version:

```bash
npm deprecate @thekaveh/vmx@2.6.1 "broken release; use 2.6.2"
```

Then publish a fix as a new patch version.

## 5. Tag scheme and multi-flavor coexistence

TypeScript releases use `typescript-v<X.Y.Z>`. Each flavor tag prefix is
independent; `release.yml` filters by prefix, so pushing a `typescript-v*`
tag never affects the Python, C#, or Swift jobs. See `langs/python/RELEASING.md`
§5 for the multi-flavor scheme overview.

## 6. Spec compatibility

`__minSpecVersion__` in `langs/typescript/src/version.ts` declares the minimum
`spec/VERSION` this package implements. Bump it manually when a new spec
version introduces breaking changes that the package now implements. A spec
major bump requires a corresponding flavor major bump per `README.md` §6.1.
