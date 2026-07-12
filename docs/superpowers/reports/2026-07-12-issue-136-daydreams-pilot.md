# Issue #136 DayDreams consumer pilot

Date: 2026-07-12

## Result

The TypeScript `AggregateChangeStream` API is applicable to both DayDreams
renderers. In a disposable clone, the Three and Babylon adapters retained their
exact initial/add/remove reconciliation while replacing the unsafe shared-hub
`PropertyChangedMessage` cast with `AggregateChangeReason.Item` and its typed
`CellVM` identity. Focused tests demonstrate that unrelated hub messages and
model changes from removed or replaced cells no longer repaint a renderer.

This was an evidence-only pilot. Nothing was committed or pushed to DayDreams.

## Reproduction inputs

- DayDreams repository: `thekaveh/daydreams`
- Pinned commit: `37b899dde1739c02cb5459ec5cd7d674495783d5`
- Disposable clone: `/tmp/daydreams-issue136-pilot` (deleted after capture)
- VMx package: `@thekaveh/vmx` `3.18.0`
- Package artifact: `/tmp/vmx-issue136-package/thekaveh-vmx-3.18.0.tgz`
- Artifact SHA-256:
  `a8d7b15dbdf3bccc14c7225594302153046287c70ca817ffb628b43d67e1aa2e`
- Runtime: Bun `1.3.14`, Node `v24.1.0`

The final verified dependency topology was deliberately mixed:

- `renderer-three` and `renderer-babylon` resolved the VMx `3.18.0` tarball and
  declared `rxjs` directly;
- `viewmodel`, `shells/web`, and `spikes/bakeoff` retained the repository's
  vendored VMx `3.1.0` dependency; and
- the aggregate consumed the older collection and `CellVM` instances through
  structural `snapshot`, membership-subscription, and local-property-stream
  contracts, so the integration did not depend on shared class identity across
  the two installed VMx versions.

The user-owned DayDreams checkout remained on `develop` at `37b899d`; its
pre-existing dirty and untracked files were not read, edited, staged, cleaned,
or removed.

## Pilot patch

The disposable patch is reproducible from the pinned commit and the artifact
above. A binary-safe capture contained 857 lines and had SHA-256
`748f4429d64a1f478878380cea9ae6fc8b80479ee9ddd218a4ed612dd1a2085b`.

```text
 bun.lock                                           | 318 +++++----------------
 packages/view/renderer-babylon/package.json        |   3 +-
 packages/view/renderer-babylon/src/index.ts        |  22 +-
 packages/view/renderer-babylon/src/reconcile.ts    |  44 +++
 .../view/renderer-babylon/tests/reconcile.test.ts  |  72 +++++
 packages/view/renderer-three/package.json          |   3 +-
 packages/view/renderer-three/src/reconcile.ts      |  48 ++--
 .../view/renderer-three/tests/reconcile.test.ts    |  34 +++
 8 files changed, 264 insertions(+), 280 deletions(-)
```

Exact `--numstat`:

```text
71  247 bun.lock
2   1   packages/view/renderer-babylon/package.json
7   15  packages/view/renderer-babylon/src/index.ts
44  0   packages/view/renderer-babylon/src/reconcile.ts
72  0   packages/view/renderer-babylon/tests/reconcile.test.ts
2   1   packages/view/renderer-three/package.json
32  16  packages/view/renderer-three/src/reconcile.ts
34  0   packages/view/renderer-three/tests/reconcile.test.ts
```

Production source, excluding manifests, lockfile, and tests, changed by 83
additions and 31 deletions: a net **+52 bespoke lines**. Most of the increase is
the new Babylon reconcile extraction, which makes that engine's wiring directly
testable without constructing a Babylon engine. A production adoption could
centralize the identical 31-line aggregate/membership adapter in the shared
renderer-contract package to remove the duplication.

## Implemented shape

Each adapter performs the same sequence:

1. Reconcile the initial `world.cells` snapshot through `onAdd`.
1. Adapt the pinned DayDreams collection to the new read-only membership
   capability with `snapshot()` and `subscribeMembership()`.
1. Construct `AggregateChangeStream<CellVM>` with a selector narrowed to each
   member's local `propertyChanged` stream where the property is `model`.
1. Repaint only on `AggregateChangeReason.Item`, using `change.item` directly.
1. Keep precise collection add/remove identities from the collection's local
   `CollectionChangedMessage` stream.
1. On renderer unsubscribe, detach the membership and item subscriptions and
   dispose the aggregate.

The aggregate subscribes to membership before the renderer's add/remove
callback subscription. A collection mutation therefore settles aggregate
membership first, then performs the existing renderer add/remove callback.
Initial callbacks remain synchronous and occur before ongoing subscriptions,
matching the previous Three and Babylon behavior.

## Test evidence

TDD red evidence was captured before the implementation:

- Three's old broad hub handler delivered `CameraVM` and world-state senders to
  `onModelChanged` as if they were `CellVM` objects.
- It continued delivering model changes from identities removed or replaced in
  `world.cells`.
- Babylon had no engine-free reconcile module or focused reconcile suite.

Fresh final commands and results:

```text
cd packages/view/renderer-three
bun run typecheck && bun run test
# tsc: exit 0; Vitest: 8 files, 106/106 tests passed

cd packages/view/renderer-babylon
bun run typecheck && bun run test
# tsc: exit 0; Vitest: 5 files, 26/26 tests passed

cd packages/viewmodel
bun run typecheck && bun run test
# tsc: exit 0; Vitest: 10 files, 141/141 tests passed

git diff --check
# exit 0
```

The changed packages and repository root define no lint script, so no lint
command was available to run. The existing Three suite printed its pre-existing
`Multiple instances of Three.js` warning; all tests still passed.

Focused coverage includes:

- initial cells, streamed adds, removals, existing-cell model swaps, and
  height-field-triggered repaints;
- unrelated camera and world-state hub traffic remaining silent;
- removed and replaced cell identities remaining silent after detachment;
- unsubscribe preventing subsequent add/remove/item callbacks; and
- equivalent engine-free reconciliation coverage for Babylon.

## API friction and applicability notes

1. The pinned DayDreams VMx dependency is `3.1.0`, before
   `ObservableMembershipSource`. Its collection therefore required a small
   structural adapter around `toArray()` and `collectionChanged`. Once DayDreams
   upgrades its VMx dependency, `world.cells` implements the capability
   directly and the adapter can disappear.
1. An intermediate attempt to replace every DayDreams VMx dependency with
   `3.18.0` exposed a separate source-compatibility migration: six DayDreams VM
   subclasses redeclare `hub` as a field while VMx now exposes it as an
   inherited accessor (`TS2610`). That intermediate topology was discarded.
   The final verified patch resolves `3.18.0` only in the two renderer packages;
   `viewmodel`, `shells/web`, and `spikes/bakeoff` continue resolving the
   vendored `3.1.0` package. A real repository-wide VMx upgrade should remove
   those redundant field declarations in one coordinated change.
1. Because the final pilot intentionally had two VMx package instances,
   cross-version `instanceof PropertyChangedMessage` checks are not valid. The
   cell aggregate avoids them entirely through structural source and selected
   stream contracts. Three's separate overlay subscription was changed to its
   equivalent structural `propertyName` plus sender-identity guard so its
   existing manifest/focus behavior remained testable under the mixed topology.
1. `AggregateChangeStream.forComponents(...)` is intentionally too broad for
   this consumer because it observes every local VM property change, including
   lifecycle properties during disposal. The explicit selector filtering
   `propertyChanged` to `model` exactly preserves the old repaint contract.
1. The renderer packages must declare `rxjs` directly because the selector uses
   `filter`; relying on VMx's peer dependency transitively would make the
   package contract incomplete.
1. The pilot package paths are absolute `/tmp` paths by design and are not a
   merge-ready DayDreams dependency update. A real adoption should consume the
   released `@thekaveh/vmx@3.18.0` package (or an approved workspace artifact)
   and regenerate the lockfile with DayDreams' pinned Bun version.
1. Bun `1.3.14` rewrote a large part of the existing Bun `1.2.0` lockfile. That
   mechanical churn accounts for the total patch's negative net line count and
   should not be interpreted as application-code reduction.

## Feasibility conclusion

The API removes the unsafe sender cast, supplies the exact current member
identity needed by DayDreams, detaches stale members correctly, preserves
renderer ordering and disposal, and passes all relevant consumer tests. The
pilot therefore supports accepting issue #136's DayDreams criterion. The only
adoption work outside the renderer change is the already-visible VMx dependency
migration described above.
