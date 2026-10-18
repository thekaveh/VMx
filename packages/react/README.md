# @thekaveh/vmx-react

Official React 18 and React 19 bindings for
[`@thekaveh/vmx`](https://www.npmjs.com/package/@thekaveh/vmx). The package
keeps React out of VMx core and adapts VMx hubs, commands, derived values, and
collections to React's external-store contract.

## 1. Install

```bash
npm install @thekaveh/vmx @thekaveh/vmx-react react rxjs use-sync-external-store
```

Releases are published to
[npm](https://www.npmjs.com/package/@thekaveh/vmx-react) from `react-v*` tags
on `main`, with provenance.

Compatibility for 0.1.x:

| Dependency | Supported range |
| --- | --- |
| `@thekaveh/vmx` | `^3.24.1` |
| React | `^18.3.1` or `^19.0.0` |
| RxJS | `^7.8.0` |
| `use-sync-external-store` | `^1.6.0` |
| Node.js | `>=20.5.0` |

The adapter follows independent SemVer. A core change only requires an adapter
release when it changes the adapter's supported API or compatibility range.

### 1.1 Unreleased source

To try an unreleased source line, build core and this adapter from a VMx
checkout cloned beside your project, then install the packed tarballs. Do not
link the live adapter directory: its React dev dependency can conflict with a
React 18 consumer. A tarball matches the public package payload.

```bash
npm --prefix ../VMx/langs/typescript ci
npm --prefix ../VMx/langs/typescript run build
npm --prefix ../VMx/packages/react ci
npm --prefix ../VMx/packages/react run build
rm -rf /tmp/vmx-packs && mkdir -p /tmp/vmx-packs
npm pack ../VMx/langs/typescript --pack-destination /tmp/vmx-packs
npm pack ../VMx/packages/react --pack-destination /tmp/vmx-packs
npm install /tmp/vmx-packs/thekaveh-vmx-[0-9]*.tgz \
  /tmp/vmx-packs/thekaveh-vmx-react-[0-9]*.tgz \
  react rxjs use-sync-external-store
npm ls react   # expect one React version
```

See [Installation](https://github.com/thekaveh/VMx/blob/main/docs/content/installation.md) for the other flavors.

## 2. Shared selector store

Create one store for the hub at the application composition root, pass it
through your own context, and select only what each component renders:

<!-- checked-snippet: examples/typescript/react/notes-showcase/tests/recipes/reactRecipe.test.tsx#react-store -->

```tsx
import { createVmxStore, shallowEqual, useVmx } from "@thekaveh/vmx-react";

const store = createVmxStore(app.hub);

function Summary() {
  const summary = useVmx(
    store,
    () => ({ title: app.model.title, busy: app.busy }),
    shallowEqual,
  );
  return <p>{summary.title}{summary.busy ? "…" : ""}</p>;
}
```

`createVmxStore` exposes stable `subscribe`, `getSnapshot`, and
`getServerSnapshot` functions. It connects on the first listener, disconnects
on the last, and schedules one React invalidation for a synchronous VMx hub
drain. Reconnection advances the cached revision so React's post-subscribe
check catches mutations made while disconnected or between render and commit.
`useVmx` uses `Object.is` by default; `shallowEqual` compares arrays and plain
objects one level deep. Call `store.dispose()` when the owning application scope
is permanently destroyed.

## 3. Focused hooks

```tsx
const vm = useVm(noteVm);                         // whole-VM invalidation
const title = useVm(noteVm, current => current.model.title);
const save = useCommand(noteVm.saveCommand);      // canExecute + stable execute
const rows = useVmCollection(notes);              // IVmCollection snapshot
const lines = useObservableList(consoleVm.lines); // ObservableList snapshot
const total = useDerivedProperty(summary.total);  // undefined until seeded
const resource = useAsyncResource(screen.data);   // discriminated async state
```

Collection snapshots retain the same array identity while quiet and preserve
the identity/order of VM items across add, remove, replace, reset, batch, and
move events. `useCommand` subscribes to `canExecuteChanged`; consumers do not
need a global polling render to refresh buttons. `useDerivedProperty` renders
`undefined` until the property's first value and renders that value as soon as
it arrives, including from a source that first emits after mount.

## 4. Conditional VMs and the Rules of Hooks

Do not call `useVm` conditionally or pass `null`. Mount a child component that
owns one unconditional hook call:

<!-- checked-snippet: examples/typescript/react/notes-showcase/tests/recipes/reactRecipe.test.tsx#react-optional-vm -->

```tsx
function MaybeEditor({ vm }: { vm: EditorVM | null }) {
  return vm === null ? <EmptyEditor /> : <BoundEditor vm={vm} />;
}
function BoundEditor({ vm }: { vm: EditorVM }) {
  const live = useVm(vm);
  return <Editor title={live.model.title} />;
}
```

This is safe when the selected VM appears, disappears, or changes identity and
under React StrictMode's development mount/unmount/remount cycle.

## 5. SSR, hydration, and list virtualization

Create a store per server request; never share a mutable store across requests.
Render and hydrate with the same VM snapshot. `getServerSnapshot` is stable and
the store does not connect to the hub during server rendering. Dispose the
client store with the application root.

Virtualized lists should use `useVmCollection` or `useObservableList` once at
the list boundary, use stable VM/model keys, and pass item identity into rows.
Do not create one full-list subscription per row. Bind a row's mutable VM with
`useVm` inside the row component when row-local updates are required.

## 6. Development

The contract suite covers selector render counts, render-to-subscribe mutation
catch-up, VMx hub batches, StrictMode subscription lifetime, SSR/hydration,
conditional VMs, commands, derived and async state, and collection identity. CI
repeats it on React 18 and React 19.

See [`CONTRIBUTING.md`](https://github.com/thekaveh/VMx/blob/main/CONTRIBUTING.md) for build and test commands and
[`RELEASING.md`](https://github.com/thekaveh/VMx/blob/main/packages/react/RELEASING.md) for the release runbook.
