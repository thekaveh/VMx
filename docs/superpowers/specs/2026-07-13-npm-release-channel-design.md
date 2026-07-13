# npm Release Channel Design

## 1. Objective

Publish `@thekaveh/vmx` 3.21.0 as the first public npm release from a verified
`main` commit. The channel must prove package contents, ESM and CommonJS
runtime imports, TypeScript declarations, all three public entry points,
provenance, registry availability, and exact-version installation before it
creates a GitHub Release or changes public-status documentation.

## 2. Current Evidence

- `@thekaveh/vmx` returns npm 404; registry connectivity is healthy.
- The package is 3.21.0 and implements spec 3.20.0 with 391/391 IDs.
- `npm ci`, fixture sync, both typechecks, lint, build, 808 tests, audit, and
  `npm pack --dry-run` pass.
- The dry-run contains 34 files: README/package metadata, three dual-format
  entry points and declarations, generated shared chunks, and four fixtures.
- Public entries are `.`, `./notifications`, and `./conformance`.
- This machine is not npm-authenticated. GitHub has no `npm-typescript`
  environment and no npm publishing secret.
- npm trusted publishing requires an existing package, npm >=11.5.1,
  Node >=22.14, a GitHub-hosted runner, and `id-token: write`.

## 3. Approaches Considered

### 3.1 Bootstrap token, then trusted publishing — selected

Create a protected `npm-typescript` environment. The first tag uses a narrowly
scoped granular token in that environment and `npm publish --provenance --access public`. After the package exists, configure npm trust for
`thekaveh/VMx`, workflow `release.yml`, environment `npm-typescript`, remove the
token, and use OIDC for every later release.

This is the only approach that gives the first immutable version provenance
while converging immediately on tokenless publishing.

### 3.2 Manual local bootstrap — rejected

A local `npm publish` can reserve the package, but it cannot produce the same
GitHub Actions provenance evidence and creates a different release path for
the most sensitive version.

### 3.3 Permanent automation token — rejected

This can publish 3.21.0 but leaves a long-lived write credential after npm can
authenticate the exact workflow through OIDC.

## 4. Package Verification Architecture

`tools/check-typescript-package.py` runs `npm pack --dry-run --json` and checks
an explicit allowlist. Stable entry-point, metadata, and fixture files are
required exactly. Hash-named tsup chunks are accepted only through narrow
filename patterns. Any source, test, config, secret, or unexpected artifact
fails the gate.

`tools/smoke-npm-consumer.py` builds a disposable consumer. In local mode it
packs the current package and installs the tarball. In public mode it polls npm
for the exact version before installing `@thekaveh/vmx@X.Y.Z`. It then:

1. imports `.`, `./notifications`, and `./conformance` as ESM;
1. requires the same entries as CommonJS;
1. compiles a NodeNext TypeScript source against their declarations;
1. checks `__version__` and representative exports;
1. removes the temporary consumer unless explicitly retained.

TypeScript CI runs this packed-consumer smoke on Node 20 and 22. The release job
uses Node 24 with npm 11.5.1, and public verification repeats on Node 20 and 22.

## 5. Release Workflow

The `typescript` release job verifies main ancestry and exact tag/package
version before authentication. It disables release caching, installs npm
11.5.1, runs fixture sync, both typechecks, lint, build, tests, audit, the
allowlist, and the local packed-consumer smoke.

Publishing has two mutually exclusive steps:

- if `NPM_TOKEN` exists, map it to `NODE_AUTH_TOKEN` only for the bootstrap
  publish and use `--provenance --access public`;
- otherwise invoke tokenless `npm publish --access public`, which npm 11.5.1+
  authenticates through the configured trusted publisher and automatically
  attests.

The workflow never green-skips publication. A separate Node 20/22 verification
matrix polls the registry and runs the exact public-consumer smoke. Only after
both cells pass does a final job extract the 3.21.0 changelog section and create
the GitHub Release.

## 6. Documentation and Recovery

The preparation PR updates only the TypeScript changelog and release runbook;
it does not claim npm availability. After public verification, a second PR pair
updates README, compatibility matrix, TypeScript README, installation guide,
TypeScript flavor page, and getting-started guide, then verifies repo/site/wiki
and their live deployments.

Package versions and tags are immutable. A pre-publish failure is fixed on a
new `main` commit and uses a new patch version if the tag already exists. A
published bad version is deprecated, never overwritten. Public docs and issue
completion require npm registry visibility, provenance, exact-version clean
installs, GitHub Release notes, and live three-surface documentation.

## 7. External Gate

Repository preparation can be completed without npm credentials. The first
publish cannot occur until an authenticated owner supplies a narrowly scoped
bootstrap token through the protected environment. No token is requested in
chat, written to disk, printed, or inferred. If the gate remains unavailable,
#57 stays Todo/Ready with evidence and dependent tickets #80/#84/#96 remain
blocked; work continues only on independent release tickets.
