# 3.7. Upgrading TypeScript and React Consumers

This page collects the upgrade work that real React consumers hit when they
moved an older VMx line onto the current TypeScript source and the official
React adapter. It turns the
[2026-08-10 consumer pilot ledger](../../maintenance/2026-08-10-vmx-react-consumer-pilots.md)
into recipes. The ledger stays the evidence; its counts are historical pilot
results, not current consumer numbers.

Every example below compiles and runs in the React adapter's test suite
(`packages/react/tests/migration.test.tsx`). A "before" shape that no longer
compiles is pinned there with `@ts-expect-error`, so this page fails its checks
if the core changes again.

## 3.7.1. Versions

| Package               | Source line in the pilots                    | Target | Target availability                       |
| --------------------- | -------------------------------------------- | ------ | ----------------------------------------- |
| `@thekaveh/vmx`       | 3.1.0 (vendored by NNx); 3.24.0 pilot builds | 3.26.0 | Source only: npm publication waits on #57 |
| `@thekaveh/vmx-react` | none: each consumer had local hooks          | 0.1.1  | Source only: published after the core     |

The targets match the [installation table](../installation.md). Until the
packages are on npm, install them from packed tarballs as described in
section 3.7.6. Each recipe repeats the versions it applies to.

## 3.7.2. Remove redundant `hub` members

**From** core before 3.10.0 **to** core 3.26.0 (source only).

Core 3.10.0 added a public read-only `hub` accessor to every component VM
(`IComponentVM.hub`). Consumer classes written against older lines often stored
and exposed the injected hub themselves. NNx had 24 such getters and DayDreams
six fields. After the upgrade:

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
core 3.24.1 or later (both source only).

NNx bound components through a local hook that took a list of property names.
The official `useVm(vm, selector, equality)` renders only when the selected
value changes. A local hook that subscribes to the whole VM and copies fields
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

**From** consumer-local list hooks **to** `@thekaveh/vmx-react` 0.1.1 (source
only).

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

The pilots kept these wrappers in the consumer on purpose. They encode product
rules, so VMx does not ship them; each is marked **consumer-local**.

- **NNx `useVmList`** (consumer-local): a list helper over the official hooks.
- **Tableau's refresh store** (consumer-local): a synchronous recomputation
  store with its own invalidation input. `createVmxStore` has no pre-invalidation
  transform, so it cannot replace this store without changing timing.
- **DayDreams' hub-first store cache** (consumer-local): it shares one store,
  and so one hub subscription, per hub for call sites that start from a hub
  rather than a VM:

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
3.26.0 and adapter 0.1.1 (source only).

Linking the adapter directory into a React 18 application resolved the
adapter's React 19 development dependency beside the application's React and
failed with an invalid hook call. A packed tarball has the same shape npm
publishes and carries no development dependencies.

```bash
# Before: a live link pulls the adapter checkout's own React
bun add ../VMx/packages/react
```

```bash
# After: pack, then install the tarballs (full steps in the installation page)
npm pack ../VMx/langs/typescript --pack-destination /tmp/vmx-packs
npm pack ../VMx/packages/react --pack-destination /tmp/vmx-packs
npm install /tmp/vmx-packs/thekaveh-vmx-3.26.0.tgz \
  /tmp/vmx-packs/thekaveh-vmx-react-0.1.1.tgz
npm ls react   # one React version
```

The complete build-and-pack sequence is in the
[installation page](../installation.md). Switch to plain `npm install` only
after the packages are published.

## 3.7.7. Codemods

No codemod ships. One would first need defined syntax boundaries, idempotent
output, a dry-run review mode, and at least two validated consumer migrations.
The pilots changed few enough lines (+13/-6 in NNx's migrated component) that
the recipes above are the supported path.

## 3.7.8. Other flavors

The pilots were TypeScript and React only; they do not show that other flavors
break in the same way. Each flavor records its own migration notes in its
changelog:
[C#](https://github.com/thekaveh/VMx/blob/main/langs/csharp/CHANGELOG.md),
[Python](https://github.com/thekaveh/VMx/blob/main/langs/python/CHANGELOG.md),
[TypeScript](https://github.com/thekaveh/VMx/blob/main/langs/typescript/CHANGELOG.md),
[Swift](https://github.com/thekaveh/VMx/blob/main/langs/swift/CHANGELOG.md), and
[Rust](https://github.com/thekaveh/VMx/blob/main/langs/rust/CHANGELOG.md).
