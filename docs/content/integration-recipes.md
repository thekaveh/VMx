# 9. Integration Recipes

The repo already carries framework-specific integration notes under
`docs/integration/`. This page is the site-level router for those recipes, not a
duplicate cookbook.

## What The Recipes Cover

Each recipe summarizes the same adapter problem:

- bridge VMx property-change events into the host framework's reactivity model
- route host actions back into `RelayCommand` or related command surfaces
- keep collection updates and dispatcher marshalling inside the adapter boundary

## Current Recipes

### C\#

- [Avalonia](../integration/avalonia.md)
- [WPF](../integration/wpf.md)
- [MAUI](../integration/maui.md)

### Python

- [Textual](../integration/textual.md)
- [NiceGUI](../integration/nicegui.md)
- [tkinter](../integration/tkinter.md)

### TypeScript

- [React](../integration/react.md)
- [Vue 3](../integration/vue.md)
- [Svelte](../integration/svelte.md)
- [SolidJS](../integration/solid.md)

### Swift

- [SwiftUI](../integration/swiftui.md)

## Imperative Engine And Uniform Bridge

Imperative engines do not need a render loop to poll VM state. Subscribe to the
selected value once, update the engine only when it changes, and let the host
adapter own the returned handle:

```typescript
const exposureSubscription = subscribeValue(
  cameraVm,
  vm => vm.model.exposure,
  exposure => { material.uniforms.exposure.value = exposure; },
  { fireImmediately: true },
);
```

Dispose the bridge with the adapter that owns `material`:

```typescript
exposureSubscription.unsubscribe();
```

When installed during adapter setup, the immediate callback establishes the
uniform before that adapter starts its first frame. Unconditionally, VMx invokes
the immediate callback synchronously before attaching the hub subscription. It
receives the selected value as both current and previous; later callbacks
receive the changed current value and the prior selected value. The selector is
reevaluated after any property message from this fixed `cameraVm`; `Object.is`
suppresses unchanged selections by default, and the `equality` option can
provide a domain-specific comparison.

The bridge is change-driven rather than frame-polled, so the renderer does no
selector work on quiet frames. Hub batches still deliver every property
message, but repeated deliveries that all see the same final exposure snapshot
collapse through equality. Initial setup failures propagate before attachment;
delivery failures use the hub's isolated subscriber-error path.

This recipe intentionally observes one fixed VM. Collection-member discovery
and dynamic fan-in remain VMx issue #136.

## Standards-Track JavaScript Signals Posture

As verified on 2026-07-12, the
[official TC39 Signals proposal](https://github.com/tc39/proposal-signals) and
[proposal tracker](https://github.com/tc39/proposals/blob/main/stage-1-proposals.md)
classify Signals as Stage 1. VMx therefore keeps RxJS as its TypeScript reactive
primitive and does not ship a Signal polyfill, `toSignal` helper, or supported
Signal subpath. Proposal-repository phases and prototype milestones are project
planning; only committee-approved TC39 stage advancement is standards status.

The existing interop seams remain the supported path:

- typed hub messages for cross-VM observation, transactions, and isolated
  subscriber failures;
- VM-local property streams for an adapter that already owns one VM;
- `DerivedProperty` for explicit computed reactive state;
- `subscribeValue` for fixed-source selected state, equality, initial delivery,
  current/previous values, and deterministic teardown;
- framework recipes and adapters that translate those notifications into the
  host's rendering primitive.

ADR-0101 requires three gates before VMx reconsiders supported Signals interop:
TC39 Stage 2 or later, a stable production-grade implementation, and successful
pilots in at least two independent VMx consumers or framework adapters. A future
design must also settle ownership/disposal, batching, equality, scheduling,
error routing, and duplicate graph/polyfill behavior. Until then, use the
ordinary VMx seams above rather than creating a second reactive architecture.

## Worked Examples

- Avalonia Notes Workspace:
  [examples/csharp/avalonia/NotesShowcase/README.md](../../examples/csharp/avalonia/NotesShowcase/README.md)
- Textual Notes Workspace:
  [examples/python/textual/notes_showcase/README.md](../../examples/python/textual/notes_showcase/README.md)
- React Notes Workspace:
  [examples/typescript/react/notes-showcase/README.md](../../examples/typescript/react/notes-showcase/README.md)
- Swift Notes Workspace:
  [examples/swift/notes-showcase/README.md](../../examples/swift/notes-showcase/README.md)

## Source Index

For the full recipe table and the common adapter pattern, use
[docs/integration/README.md](../integration/README.md).
