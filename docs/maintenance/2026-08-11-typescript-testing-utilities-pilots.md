# TypeScript Testing Utilities Consumer Pilots

## 1. Scope

Issue #84 was validated against a real packed `@thekaveh/vmx` 3.24.0 artifact
in disposable clones of NNx Studio and Tableau. Neither consumer repository was
modified, committed, or pushed. The pilots measure only executable lines:
blank lines and comment-only lines are excluded by the same `awk` predicate in
both before/after counts.

VMx source: `d8946a18ca1ec49babdf4fb45bb768142a05fb9a` plus the uncommitted #84
worktree. Packed artifact:
`/private/tmp/vmx-issue84-packs/thekaveh-vmx-3.24.0.tgz`.

## 2. NNx Studio

- Source revision: `e1569caa869925ac6f99eab8fb53f80543e8d183`.
- Disposable clone: `/private/tmp/vmx-issue84-pilot-nnx-20260811`.
- Representative file:
  `packages/viewmodel/tests/diffusionSetupVM.test.ts`.
- Migration: two direct service constructions became one
  `createTestServices()` call. Two hand-written `PropertyChangedMessage`
  subscriptions became filtered `recordPropertyChanges()` recorders with
  explicit disposal.
- Executable LOC: 77 before, 72 after (5 lines / 6.5% removed).
- Focused behavior: 7 of 7 tests passed before and after.
- Final typecheck: passed after applying the already-known VMx 3.24.0 consumer
  compatibility adjustment (`override` on 24 inherited `hub` getters) only in
  the disposable clone. That adjustment is unrelated to the testing API and is
  not included in the LOC result.

Commands:

```bash
# Baseline, real repository
packages/viewmodel/node_modules/.bin/vitest run \
  packages/viewmodel/tests/diffusionSetupVM.test.ts

# Packed pilot
pnpm install --ignore-scripts
packages/viewmodel/node_modules/.bin/tsc \
  -p packages/viewmodel/tsconfig.json --noEmit
packages/viewmodel/node_modules/.bin/vitest run \
  packages/viewmodel/tests/diffusionSetupVM.test.ts
```

## 3. Tableau

- Source revision: `2326d7e3cd94f7d8fab0d64e1adb9f0b1dbd62da`.
- Disposable clone: `/private/tmp/vmx-issue84-pilot-tableau-20260811`.
- Representative file: `frontend/view/react/tests/CommandDeck.test.tsx`.
- Migration: four structural command objects became `CommandDouble` /
  `CommandDoubleOf<T>` instances. Invocation assertions read semantic execution
  records, and the disabled case uses `setCanExecute(false)` instead of
  replacing the complete command set.
- Executable LOC: 70 before, 67 after (3 lines / 4.3% removed).
- Focused behavior: 4 of 4 tests passed before and after.
- Final `@tableau/view-react` typecheck: passed.

Commands:

```bash
# Baseline, real repository
frontend/node_modules/.bin/vitest run \
  view/react/tests/CommandDeck.test.tsx

# Packed pilot, from the disposable clone's frontend directory
npm install --ignore-scripts
node_modules/.bin/vitest run view/react/tests/CommandDeck.test.tsx
npm run typecheck --workspace @tableau/view-react
```

The disposable Tableau install reported five existing high-severity audit
findings in the consumer dependency tree. The pilot did not change or waive
those dependencies; VMx's own locked audit is a separate release gate.

## 4. Findings

The public surface covers both tested consumer shapes without a runner peer:
service setup and property observation in NNx, and stateful command doubles in
Tableau. No additional #84 primitive was required by either migration.

NNx's inherited-`hub` override drift remains a consumer upgrade task already
identified during #80; it does not arise from `@thekaveh/vmx/testing`. The
pilots also confirm why helpers must expose records instead of matcher methods:
both consumers retain their existing Vitest assertions while their VMx-specific
mechanics disappear.

## 5. Repository integrity

After both pilots, these commands returned no changes:

```bash
git -C /Users/kaveh/repos/nnx-studio status --short
git -C /Users/kaveh/repos/tableau status --short
```

The clones and package tarball are disposable evidence only and are not part of
the VMx commit.
