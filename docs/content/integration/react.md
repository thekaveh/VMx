# 9.8. React Integration

`@thekaveh/vmx-react` is the official React 18 and React 19 adapter for
`@thekaveh/vmx`. It keeps React out of the language-neutral core while giving
applications a StrictMode-safe, server-rendering-safe external-store boundary.
The source package is complete; public npm publication follows the first public
core package tracked by issue #57.

## 9.8.1. Reactivity primitive

The adapter uses React's `useSyncExternalStore` contract. A `VmxStore` owns one
lazy subscription to a VMx hub, exposes stable subscribe and cached monotonic
snapshot functions, and coalesces one synchronous hub drain into one React
invalidation. Subscribe-time catch-up closes mutations made while disconnected
or between render and commit. `useVmx` applies a selector with `Object.is` by
default or an explicit equality function such as `shallowEqual`.

## 9.8.2. Mapping

| React binding                           | VMx source                                        |
| --------------------------------------- | ------------------------------------------------- |
| `createVmxStore` / `useVmx`             | one shared `IMessageHub` selector boundary        |
| `useVm`                                 | sender-filtered component or form VM updates      |
| `useCommand`                            | `ICommand.canExecuteChanged` and stable execution |
| `useObservableList` / `useVmCollection` | identity-preserving collection snapshots          |
| `useDerivedProperty`                    | pushed derived values, including unseeded state   |
| `useAsyncResource`                      | discriminated async-resource state                |

## 9.8.3. Install and create the shared store

```bash
npm install @thekaveh/vmx @thekaveh/vmx-react react rxjs use-sync-external-store
```

Until publication, follow the
[pack-then-install source procedure](../installation.md);
do not link a live adapter checkout into a React 18 application. Create one
store at the application composition root:

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

Call `store.dispose()` only when the owning application scope is permanently
destroyed. React mount cleanup is managed by the hooks.

## 9.8.4. Focused bindings and conditional VMs

Use the narrowest binding that represents what the component renders:

```tsx
const title = useVm(noteVm, vm => vm.model.title);
const save = useCommand(noteVm.saveCommand);
const notes = useVmCollection(workspace.notes);
const total = useDerivedProperty(workspace.total);
const resource = useAsyncResource(screen.data);
```

`useCommand` accepts an `ICommand` separately from its owning VM. Invoke the
stable callback returned by the binding; the equivalent direct VMx intent is
`saveCommand.execute()`.

Never call a hook conditionally or pass `null`. Mount a child which owns one
unconditional binding when a VM is optional:

```tsx
function MaybeEditor({ vm }: { vm: EditorVM | null }) {
  return vm === null ? <EmptyEditor /> : <BoundEditor vm={vm} />;
}
function BoundEditor({ vm }: { vm: EditorVM }) {
  const live = useVm(vm);
  return <Editor title={live.model.title} />;
}
```

The same `useVm` contract applies to `FormVM`; a shared-store selector is useful
when a component combines form state with other application state.

## 9.8.5. StrictMode, SSR, hydration, and virtualization

The store connects on the first listener and disconnects on the last, including
React StrictMode's development remount. Create a store per server request,
render and hydrate from the same VM snapshot, and never share mutable server
stores between requests. `getServerSnapshot` does not subscribe during server
rendering.

Virtualized lists should bind once with `useVmCollection` or
`useObservableList`, use stable model keys, and pass item identities into rows.
Rows that display mutable VM state may call `useVm` locally.

## 9.8.6. Flagship and release policy

[`examples/typescript/react/notes-showcase/`](../../../examples/typescript/react/notes-showcase/)
is the Notes Workspace React 19 flagship. It consumes the official package
while keeping only application-specific browser adapters in the example.

The adapter follows independent SemVer under `react-v*` tags. Core releases do
not force adapter releases unless its public API or compatibility range changes.
See [`packages/react/RELEASING.md`](../../../packages/react/RELEASING.md).

## 9.8.7. Serialize Portal Dialog Requests

Keep portal overlay state in an external observable store just like VM state,
but do not model it as one replaceable request slot. The flagship
`ReactDialogService` retains one active request and a FIFO queue. Each modal
resolver settles only its own promise and publishes the next request (or `null`)
to `useSyncExternalStore`. Explicit close uses the operation's neutral result
(`false`, `null`, or completion) and advances the same queue.

This is the queueing policy permitted by DIA-006. It prevents a second confirm,
file picker, or notification from replacing the active request and leaving the
first caller pending forever. See
[`ReactDialogService.tsx`](../../../examples/typescript/react/notes-showcase/src/views/adapter/ReactDialogService.tsx)
and its two-call settlement tests.
