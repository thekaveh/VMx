# 9.1. Integration Recipes

These framework-specific recipes are canonical documentation: the same pages
render in the repository, the `.io` site, and the GitHub wiki.

## 9.1.1. What The Recipes Cover

Each recipe summarizes the same adapter problem:

- bridge VMx property-change events into the host framework's reactivity model
- route host actions back into `RelayCommand` or related command surfaces
- keep collection updates and dispatcher marshalling inside the adapter boundary

## 9.1.2. Current Recipes

### 9.1.2.1. C\#

- [Avalonia](avalonia.md)
- [WPF](wpf.md)
- [MAUI](maui.md)

### 9.1.2.2. Python

- [Textual](textual.md)
- [NiceGUI](nicegui.md)
- [tkinter](tkinter.md)

### 9.1.2.3. TypeScript

- [React](react.md)
- [Vue 3](vue.md)
- [Svelte](svelte.md)
- [SolidJS](solid.md)

### 9.1.2.4. Swift

- [SwiftUI](swiftui.md)

## 9.1.3. Imperative Engine And Uniform Bridge

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

This recipe intentionally observes one fixed VM. For collection-member
discovery and dynamic fan-in, use `AggregateChangeStream` (ADR-0098).

## 9.1.4. Standards-Track JavaScript Signals Posture

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

## 9.1.5. Worked Examples

- Avalonia Notes Workspace:
  [examples/csharp/avalonia/NotesShowcase/README.md](../../../examples/csharp/avalonia/NotesShowcase/README.md)
- Textual Notes Workspace:
  [examples/python/textual/notes_showcase/README.md](../../../examples/python/textual/notes_showcase/README.md)
- React Notes Workspace:
  [examples/typescript/react/notes-showcase/README.md](../../../examples/typescript/react/notes-showcase/README.md)
- Swift Notes Workspace:
  [examples/swift/notes-showcase/README.md](../../../examples/swift/notes-showcase/README.md)
