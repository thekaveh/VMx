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
