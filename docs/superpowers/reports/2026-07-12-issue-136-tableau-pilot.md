# Issue 136 Tableau Aggregate-Change Pilot

## 1. Outcome

The Tableau pilot is feasible with the public VMx 3.18.0 API. In a disposable
clone, `canvasVm` replaced its revision counter, state-sender `Set`, broad hub
filter, and manual defer-depth fan-in with `AggregateChangeStream<HexNode>` over
the already-supported internal `cellComposite`. The selector is the nested
`node.model.state.propertyChanged` stream.

The consumer source change is 21 insertions and 55 deletions, a net reduction
of 34 production lines. Six focused tests add 91 lines. No VMx source edit or
consumer-specific aggregate API was required.

This was validation only. Nothing was committed or pushed to Tableau.

## 2. Reproducible Inputs And Isolation

- Tableau commit: `50f562a2e40a344a6f4ceaf0999aedd82d679b3f`
  (`develop` commit supplied for the pilot; clone used detached HEAD).
- VMx package: `thekaveh-vmx-3.18.0.tgz`.
- Package SHA-256:
  `a8d7b15dbdf3bccc14c7225594302153046287c70ca817ffb628b43d67e1aa2e`.
- The package was unpacked into the disposable clone's vendored VMx package
  location because this Tableau commit resolves `@thekaveh/vmx` through that
  file dependency.
- The user Tableau checkout was read only and retained the same branch, HEAD,
  and status observed before the pilot.

Placeholders used below:

```text
$PILOT    disposable Tableau clone
$VMX_TGZ  thekaveh-vmx-3.18.0.tgz
```

## 3. Exact Pilot Patch And Size

Only these consumer files comprise the implementation/test patch:

```text
 frontend/view-model/src/canvasVm.ts           | 76 +++++++---------------
 frontend/view-model/tests/projections.test.ts | 91 +++++++++++++++++++++++++++
 2 files changed, 112 insertions(+), 55 deletions(-)
```

Exact numstat:

```text
21  55  frontend/view-model/src/canvasVm.ts
91   0  frontend/view-model/tests/projections.test.ts
```

The saved unified diff SHA-256 before clone removal was
`55112e0628510bb7263cfcd6d91bf2100c7a33c7b7a2c6e6e0f8fb6caefb8e46`.
`git diff --check` passed.

The production patch:

1. creates `AggregateChangeStream(cellComposite, node => node.model.state.propertyChanged)`;
1. publishes `observe({ emitInitial: true })` as `cellsChanged`;
1. retains the precise `ObservableList`-to-`cellComposite` structural mirror,
   because `ObservableList` is intentionally not an aggregate membership
   source;
1. batches Replace and Reset resynchronization;
1. uses item provenance only for the existing pending-filter refresh;
1. wraps each root/child creation through final tree attachment in
   `cellChanges.withBatch(...)`, so subscribers receive one final pulse after
   paths are valid; and
1. explicitly disposes the aggregate before its membership source.

## 4. Acceptance Evidence

The original focused suite passed 9/9 before edits. Tests were then added before
the production replacement. The old sender-`Set` implementation produced the
expected red result:

```text
Test Files  1 failed (1)
Tests       1 failed | 14 passed (15)
duplicate identity: expected 4 emissions, received 3
```

Removing the first of two identical members deleted the sender from the old
`Set`, so the remaining identical member became incorrectly silent. After the
aggregate replacement:

```text
Test Files  1 passed (1)
Tests       15 passed (15)
```

The focused cases prove:

- an initial emission for every subscriber, together with the existing initial
  `protectedPedigree` computation assertions;
- one generated-child and root pulse only after tree attachment;
- nested cell-state changes;
- silence after remove and Reset;
- duplicate object-identity refcounting through first removal; and
- one final pulse for the explicit add/attachment batch.

The complete view-model test directory also passed:

```text
Test Files  14 passed (14)
Tests       103 passed (103)
```

## 5. Commands And Results

All commands ran from `$PILOT/frontend` unless shown otherwise.

```text
tar -xzf "$VMX_TGZ" --strip-components=1 \
  -C vendor/VMx/langs/typescript
npm install
```

Passed; the requested 3.18.0 package was the installed file dependency.

```text
npx vitest run view-model/tests/projections.test.ts
```

Passed, 15/15 after the red/green cycle above.

```text
npm run typecheck --workspace @tableau/view-model
```

Passed.

```text
npx vitest run view-model/tests
```

Passed, 14 files and 103 tests.

```text
npm run typecheck
```

Passed across model, services, view-model, canvas, React, shared, desktop, web,
and preview workspaces.

```text
npm run lint --workspace @tableau/view-model --if-present
npm pkg get scripts.lint --workspace @tableau/view-model
```

The first command completed without a lint run; the second returned
`{"@tableau/view-model": {}}`. This pinned package has no native lint script.

```text
npm test --workspace @tableau/view-model
```

The package-local script is pre-existingly mis-rooted: Vitest looked for
`frontend/view-model/view/react/vitest.config.ts`. The documented root-level
runner above is the working package verification path.

```text
npm test
```

With VMx 3.18.0, the full frontend run reported 48 passed files, one skipped,
two failed; 363 passed tests, one skipped, and three failed. The failures were
`view/react/tests/CreatePanelReactive.test.tsx` (two) and
`view/react/tests/commandDeckAxis.test.tsx` (one). All enter a pre-existing
FormVM/MessageHub publish cycle and trip the 10,000-message drain guard; no
aggregate or `canvasVm` frame appears in the causal stack.

Two disposable controls isolated this from the pilot patch:

- unmodified Tableau at the same commit with its pinned VMx 3.1.0 passed the
  full suite: 50 passed files, one skipped; 360 passed tests, one skipped;
- unmodified Tableau at the same commit with only VMx replaced by the 3.18.0
  artifact reproduced the identical three React failures: 48 passed files,
  one skipped, two failed; 357 passed tests, one skipped, three failed.

The six-test count difference between the latter control and the pilot run is
exactly the focused coverage added by this pilot.

## 6. API Fit And Friction

The API fits the motivating Tableau use without an extension:

- `CompositeVM` is the correct supported dynamic-membership source.
- The selector accepts Tableau's nested state stream directly; it does not
  force observation of `HexNode.propertyChanged`.
- Subscriber-local `emitInitial` preserves the former `BehaviorSubject`
  initialization contract without carrying a meaningless revision number.
- `withBatch` is sufficient to preserve post-tree-attachment timing and to
  collapse multi-signal Replace/Reset synchronization.
- Item provenance lets the pending projection refresh only on cell-state
  changes while consumers needing a pulse can ignore the envelope.
- Duplicate identities and removal are handled by the aggregate's internal
  refcounts, eliminating the demonstrated sender-`Set` defect.

The remaining mirror subscriptions are domain adaptation, not fan-in: Tableau
still owns `allCells` as an indexing list while its supported `cellComposite`
is the aggregate source. The public API correctly does not treat the list as a
VM membership capability.

## 7. Caveats And Follow-Up

The aggregate pilot itself is green and requires no issue-136 API correction.
The full-suite control does reveal a separate Tableau compatibility problem
between this pinned consumer and VMx 3.18.0 in FormVM/MessageHub behavior. That
should be investigated independently before Tableau upgrades its VMx pin; it
does not justify adding a consumer-specific aggregate shortcut.

The package-local Vitest path issue and absence of a lint script are also
consumer tooling limitations at the pinned commit. Root-level typecheck and
test commands provided the authoritative pilot verification.
