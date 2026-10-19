# 3.7. Upgrading TypeScript and React Consumers

This page gives recipes for moving a React application from an older VMx line
onto the current TypeScript package and the official React adapter. The
[consumer pilot record](../../maintenance/2026-08-10-vmx-react-consumer-pilots.md)
holds the evidence behind the recipes.

Every example below compiles and runs in the React adapter's test suite
(`packages/react/tests/migration.test.tsx`). A "before" shape that no longer
compiles is pinned there with `@ts-expect-error`, so this page fails its checks
if the core changes again.

## 3.7.1. Versions

| Package               | Target | Target availability |
| --------------------- | ------ | ------------------- |
| `@thekaveh/vmx`       | 3.30.0 | Published on npm    |
| `@thekaveh/vmx-react` | 0.1.1  | Published on npm    |

Install the targets from npm as the [installation page](../installation.md)
shows. To consume an unreleased source line, use packed tarballs (section
3.7.6). Each recipe states the versions it applies to.

## 3.7.2. Remove redundant `hub` members

**From** core before 3.10.0 **to** core 3.30.0.

Core 3.10.0 and later give every component VM a public read-only `hub`
accessor (`IComponentVM.hub`). Consumer classes written against older lines
often store and expose the injected hub themselves. After the upgrade:

- a redundant `hub` **field** no longer compiles (TS2610: the base defines `hub`
  as an accessor);
- a redundant `get hub()` needs `override` under `noImplicitOverride` (TS4114).

Before (core 3.1.0):

<!-- checked-snippet: packages/react/tests/migration.test.tsx#upgrade-hub-before -->

```tsx
class LegacyRunVM extends ComponentVMOf<Run> {
  readonly hub: IMessageHub;

  constructor(hub: IMessageHub, model: Run) {
    super(runOptions(hub, model));
    this.hub = hub;
  }
}
```

After: delete the member and use the inherited `vm.hub`, which returns the
injected hub.

<!-- checked-snippet: packages/react/tests/migration.test.tsx#upgrade-hub-after -->

```tsx
class RunVM extends ComponentVMOf<Run> {
  constructor(hub: IMessageHub, model: Run) {
    super(runOptions(hub, model));
  }
}
```

Keep an `override get hub()` only when it adds behavior; a getter that merely
returns the injected hub is redundant.

## 3.7.3. Replace property-list hooks with selector projections

**From** consumer-local binding hooks **to** `@thekaveh/vmx-react` 0.1.1 over
core 3.24.1 or later.

Some consumers bind components through a local hook that takes a list of
property names. The official `useVm(vm, selector, equality)` renders only when
the selected value changes. A local hook that subscribes to the whole VM and copies fields
re-renders on every property change, including ones the component never reads:

<!-- checked-snippet: packages/react/tests/migration.test.tsx#upgrade-selector-before -->

```tsx
function useRunFields(vm: RunVM): Pick<Run, "name" | "status"> {
  useVm(vm);
  const { name, status } = vm.model;
  return { name, status };
}
```

After: select exactly what the component renders and compare with
`shallowEqual`. The test shows that an unrelated property change re-renders the
"before" component but not this one.

<!-- checked-snippet: packages/react/tests/migration.test.tsx#upgrade-selector-after -->

```tsx
const fields = useVm(
  vm,
  (current) => ({ name: current.model.name, status: current.model.status }),
  shallowEqual,
);
```

For several VMs on one hub, select from a shared `createVmxStore(hub)` with
`useVmx(store, selector, shallowEqual)`, as the
[React integration guide](../integration/react.md) shows.

## 3.7.4. Treat list snapshots as read-only

**From** consumer-local list hooks **to** `@thekaveh/vmx-react` 0.1.1.

`useObservableList` and `useVmCollection` return a cached `readonly T[]`
snapshot so React can compare renders by identity. Code that sorted or spliced
the returned array in place no longer compiles, and doing it through a cast
would corrupt the cached snapshot:

```tsx
// Before: a local hook returned a mutable array.
const items = useLocalList(list);
items.sort((left, right) => left - right); // error: readonly number[]
```

After: copy before changing the order. The source list is untouched, and the
component re-renders when the list changes.

<!-- checked-snippet: packages/react/tests/migration.test.tsx#upgrade-list-after -->

```tsx
const items = useObservableList(list);
const sorted = [...items].sort((left, right) => left - right);
```

## 3.7.5. Keep consumer-specific wrappers local

Some wrappers encode product rules, so VMx does not ship them. Keep them in
the consumer:

- **A list helper** over the official hooks.
- **A refresh store**: a synchronous recomputation store with its own
  invalidation input. `createVmxStore` has no pre-invalidation transform, so it
  cannot replace such a store without changing timing.
- **A hub-first store cache**: it shares one store, and so one hub
  subscription, per hub for call sites that start from a hub rather than a VM:

<!-- checked-snippet: packages/react/tests/migration.test.tsx#upgrade-hub-first-store -->

```tsx
const storesByHub = new WeakMap<IMessageHub, VmxStore>();
function storeForHub(hub: IMessageHub): VmxStore {
  let store = storesByHub.get(hub);
  if (store === undefined) {
    store = createVmxStore(hub);
    storesByHub.set(hub, store);
  }
  return store;
}
```

The fixture checks that two components using this cache share one hub
subscription and release it when they unmount, and that a focused `useVm`
binding releases its subscription on unmount.

## 3.7.6. Install packed tarballs, not a live directory link

**From** a directory link to a VMx checkout **to** packed tarballs of core
and adapter, when consuming an unreleased source line.

A linked adapter directory can resolve the adapter's React 19 development
dependency beside the application's React. In a React 18 application, this
fails with an invalid hook call. A packed tarball has the same shape npm
publishes and carries no development dependencies.

The TypeScript tab of the [installation page](../installation.md) gives the
complete build, pack, and install sequence, including the peer packages. For
published versions, use plain `npm install`.

## 3.7.7. Codemods

No codemod ships. A codemod needs defined syntax boundaries, idempotent output,
a dry-run review mode, and at least two validated consumer migrations. The
recipes above are the supported migration path.

## 3.7.8. Other flavors

These recipes cover TypeScript and React only. Other flavors do not
necessarily break in the same way. Each flavor records its own migration notes
in its changelog:
[C#](../../../langs/csharp/CHANGELOG.md),
[Python](../../../langs/python/CHANGELOG.md),
[TypeScript](../../../langs/typescript/CHANGELOG.md),
[Swift](../../../langs/swift/CHANGELOG.md), and
[Rust](../../../langs/rust/CHANGELOG.md).
