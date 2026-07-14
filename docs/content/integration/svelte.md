# 9.10. Svelte Integration

Wire a `ComponentVMOf<M>` to a Svelte component via Svelte 5 runes
(`$state`, `$derived`, `$effect`) or, on Svelte 4, via a custom store.

## 9.10.1. Reactivity primitive

- **Svelte 5:** `$state(value)` is a deeply reactive rune; reads in
  the template auto-track and re-render on mutation.
- **Svelte 4:** the `{ subscribe }` contract — any object with a
  `subscribe(set)` method that returns an unsubscribe function works as
  a store and is auto-tracked with the `$store` syntax.

## 9.10.2. Mapping

| Svelte                           | VMx                                  |
| -------------------------------- | ------------------------------------ |
| `$state(x)` / `writable(x)`      | `PropertyChangedMessage<T>` handler  |
| `on:click={fn}`                  | `command.execute()` in `fn`          |
| `$derived(...)` / `derived(...)` | `DerivedProperty<T>` / `fromSources` |
| `onDestroy(() => cleanup)`       | dispose the subscription             |

## 9.10.3. Adapter skeleton — Svelte 4 store

```ts
// lib/vmStore.ts
import { readable, type Readable } from "svelte/store";
import { filter } from "rxjs/operators";
import { ComponentVMOf, type IMessageHub, PropertyChangedMessage } from "@thekaveh/vmx";

export function vmStore<M, K extends keyof ComponentVMOf<M>>(
  vm: ComponentVMOf<M>,
  hub: IMessageHub,
  property: K
): Readable<ComponentVMOf<M>[K]> {
  return readable(vm[property], (set) => {
    const sub = hub.messages
      .pipe(filter((m): m is PropertyChangedMessage<unknown> =>
        m instanceof PropertyChangedMessage &&
        m.sender === vm &&
        m.propertyName === property))
      .subscribe(() => set(vm[property]));
    return () => sub.unsubscribe();
  });
}
```

```svelte
<script lang="ts">
  import { vmStore } from "$lib/vmStore";
  import type { ComponentVMOf, IMessageHub } from "@thekaveh/vmx";
  export let vm: ComponentVMOf<Note>;
  export let hub: IMessageHub;
  const model = vmStore(vm, hub, "model");
</script>

<h1>{$model.title}</h1>
<button on:click={() => vm.saveCommand.execute()}>Save</button>
```

For Svelte 5, drop the store wrapper and assign into a `$state(...)`
variable inside an `$effect(...)` that subscribes to the hub.

## 9.10.4. Fuller example

No worked Svelte Notes-Showcase ships yet. The React and Vue recipes
share the same hub-subscription shape.
