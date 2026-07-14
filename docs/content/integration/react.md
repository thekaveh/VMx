# 9.8. React Integration

Wire a `ComponentVMOf<M>` to a React component using
`useSyncExternalStore` (React 18+) — the canonical hook for subscribing
React to an external observable source.

## 9.8.1. Reactivity primitive

`useSyncExternalStore(subscribe, getSnapshot)` re-renders when the
`subscribe` callback fires its registered notifier. VMx VMs publish
`PropertyChangedMessage<T>` to their hub; we adapt the hub stream to
the `useSyncExternalStore` contract.

## 9.8.2. Mapping

| React                                | VMx                                       |
| ------------------------------------ | ----------------------------------------- |
| `useSyncExternalStore(sub, snap)`    | hub `PropertyChangedMessage` subscription |
| `onClick={() => fn()}`               | `command.execute()`                       |
| `useMemo` over a derived value       | `DerivedProperty<T>` / `fromSources`      |
| `useEffect(() => () => cleanup, [])` | dispose the subscription on unmount       |

## 9.8.3. Adapter skeleton

```ts
import { useSyncExternalStore, useCallback } from "react";
import { filter } from "rxjs/operators";
import { ComponentVMOf, PropertyChangedMessage } from "@thekaveh/vmx";
import type { IMessageHub } from "@thekaveh/vmx";

export function useVm<M, K extends keyof ComponentVMOf<M>>(
  vm: ComponentVMOf<M>,
  hub: IMessageHub,
  property: K
): ComponentVMOf<M>[K] {
  const subscribe = useCallback((notify: () => void) => {
    const sub = hub.messages
      .pipe(filter((m): m is PropertyChangedMessage<unknown> =>
        m instanceof PropertyChangedMessage &&
        m.sender === vm &&
        m.propertyName === property))
      .subscribe(() => notify());
    return () => sub.unsubscribe();
  }, [vm, hub, property]);

  return useSyncExternalStore(subscribe, () => vm[property]);
}

export function NoteView({ vm, hub }: { vm: ComponentVMOf<Note>; hub: IMessageHub }) {
  const model = useVm(vm, hub, "model");
  return <>
    <h1>{model.title}</h1>
    <button onClick={() => vm.saveCommand.execute()}>Save</button>
  </>;
}
```

## 9.8.4. Fuller example

[`examples/typescript/react/notes-showcase/`](../../examples/typescript/react/notes-showcase/) —
the Notes-Showcase React flagship: ships `useVm` / `useCommand` /
`useDerivedProperty` hooks plus a full `WorkspaceVM`-driven UI
(shipped in v2.2.0; `ThemeVM` added in v2.4.0).
