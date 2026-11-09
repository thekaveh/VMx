# React 18 dependency tree for `@thekaveh/vmx-react`

This directory is not a package. It holds the dependency tree that CI uses to
test the React adapter on React 18. The adapter's own lockfile in
`packages/react` resolves React 19.

`package.json` is a copy of `packages/react/package.json`. Only `version` and
the `react`, `react-dom`, `@types/react` and `@types/react-dom` dev dependency
ranges differ; these ranges select React 18. The `react` jobs of
`typescript.yml` copy both files into `packages/react` and run `npm ci`.
`tools/tests/test_react_adapter_automation.py` checks that the two manifests
agree.

After a change to `packages/react/package.json` or its lockfile, copy the
manifest here, restore the four React 18 ranges, and refresh the lockfile:

```bash
cd packages/react-18-deps
npm install --package-lock-only --ignore-scripts
```

Dependabot updates this directory with `packages/react` in one pull request
per dependency. It does not propose a new major version of React or its types.
