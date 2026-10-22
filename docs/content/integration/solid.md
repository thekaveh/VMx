# 9.11. SolidJS Integration

Wire a `ComponentVMOf<M>` to a Solid component through `createSignal` and
`onCleanup`, Solid's fine-grained reactivity primitives.

## 9.11.1. Reactivity primitive

- `createSignal(initial)` returns a `[get, set]` pair. Reads are tracked
  inside JSX and reactive scopes; writes trigger re-renders for any
  subscriber.
- `onCleanup(fn)` registers teardown.

## 9.11.2. Mapping

| Solid                                | VMx                                  |
| ------------------------------------ | ------------------------------------ |
| `createSignal(x, { equals: false })` | `PropertyChangedMessage<T>` handler  |
| `onClick={() => fn()}`               | `command.execute()` in `fn`          |
| `createMemo(() => ...)`              | `DerivedProperty<T>` / `fromSources` |
| `onCleanup(() => cleanup)`           | dispose the subscription             |

A [`republishModel()` announcement keeps the same reference](index.md#914-republished-models-keep-their-reference),
and a signal with the default `===` equality skips it. The hook creates the
signal with `equals: false`. Messages for another VM or another property are
filtered out.

## 9.11.3. Adapter skeleton

This is the exact file run by `examples/typescript/integration-recipes` against
`solid-js` 1.9.17, including an in-place mutation announced with
`republishModel()`, replacement and scalar updates, unrelated messages, and
cleanup.

<!-- checked-snippet: examples/typescript/integration-recipes/src/solid/NoteView.tsx -->

```tsx
import { createSignal, onCleanup, type Accessor } from "solid-js";
import { filter } from "rxjs";
import {
  type ComponentVMOf,
  type ICommand,
  type IMessageHub,
  PropertyChangedMessage,
} from "@thekaveh/vmx";
import type { Note } from "./note";

/**
 * Binds one VM property for the owning component's lifetime. `vm` and `hub`
 * are read once, so they are fixed inputs: remount (for example with a keyed
 * `<Show>`) to rebind to another VM.
 */
export function useVm<M, K extends keyof ComponentVMOf<M>>(
  vm: ComponentVMOf<M>,
  hub: IMessageHub,
  property: K,
): Accessor<ComponentVMOf<M>[K]> {
  // `equals: false`: a republished model keeps its reference but must render.
  const [value, setValue] = createSignal(vm[property], { equals: false });
  const sub = hub.messages
    .pipe(
      filter(
        (m): m is PropertyChangedMessage<unknown> =>
          m instanceof PropertyChangedMessage && m.sender === vm && m.propertyName === property,
      ),
    )
    .subscribe(() => setValue(() => vm[property]));
  onCleanup(() => sub.unsubscribe());
  return value;
}

export function NoteView(props: {
  vm: ComponentVMOf<Note>;
  hub: IMessageHub;
  saveCommand: ICommand;
}) {
  const model = useVm(props.vm, props.hub, "model");
  return (
    <>
      <h1>{model().title}</h1>
      <button onClick={() => props.saveCommand.execute()}>Save</button>
    </>
  );
}
```

`useVm` reads `vm` and `hub` once, so they are fixed for the binding's
lifetime. To show a different VM, remount the component, for example inside a
keyed `<Show>`.

## 9.11.4. Fuller example

There is no Solid Notes-Showcase. The runnable reference is
`examples/typescript/integration-recipes`. For a packaged adapter, see the
React recipe ([react.md](react.md)).
