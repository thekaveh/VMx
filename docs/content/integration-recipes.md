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

The immediate callback establishes the uniform before the first frame and
receives the selected value as both current and previous. Later callbacks
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
