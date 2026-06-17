# SolidJS integration

Wire a `ComponentVMOf<M>` to a Solid component via `createSignal` and
`createEffect` — Solid's fine-grained reactivity primitives.

## 1. Reactivity primitive

- `createSignal(initial)` returns a `[get, set]` pair. Reads are tracked
  inside JSX and reactive scopes; writes trigger re-renders for any
  subscriber.
- `createEffect(fn)` runs `fn` on every change to signals it reads.
- `onCleanup(fn)` registers teardown.

## 2. Mapping

| Solid                      | VMx                                  |
| -------------------------- | ------------------------------------ |
| `createSignal(x)` set      | `PropertyChangedMessage<T>` handler  |
| `onClick={() => fn()}`     | `command.execute(undefined)` in `fn` |
| `createMemo(() => ...)`    | `DerivedProperty<T>` / `fromSources` |
| `onCleanup(() => cleanup)` | dispose the subscription             |

## 3. Adapter skeleton

```ts
import { createSignal, onCleanup, type Accessor } from "solid-js";
import { filter } from "rxjs/operators";
import { ComponentVMOf, IMessageHub, PropertyChangedMessage } from "@thekaveh/vmx";

export function useVm<M, K extends keyof ComponentVMOf<M>>(
  vm: ComponentVMOf<M>,
  hub: IMessageHub,
  property: K
): Accessor<ComponentVMOf<M>[K]> {
  const [value, setValue] = createSignal(vm[property]);
  const sub = hub.messages
    .pipe(filter((m): m is PropertyChangedMessage<unknown> =>
      m instanceof PropertyChangedMessage &&
      m.sender === vm &&
      m.propertyName === property))
    .subscribe(() => setValue(() => vm[property]));
  onCleanup(() => sub.unsubscribe());
  return value;
}

export function NoteView(props: { vm: ComponentVMOf<Note>; hub: IMessageHub }) {
  const model = useVm(props.vm, props.hub, "model");
  return (
    <>
      <h1>{model().title}</h1>
      <button onClick={() => props.vm.saveCommand.execute(undefined)}>Save</button>
    </>
  );
}
```

## 4. Fuller example

No worked Solid Notes-Showcase ships yet. The React recipe
([react.md](react.md)) shares the same hub-subscription shape.
