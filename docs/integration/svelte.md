# Svelte integration

Wire a `ComponentVMOf<M>` to a Svelte component via Svelte 5 runes
(`$state`, `$derived`, `$effect`) or, on Svelte 4, via a custom store.

## 1. Reactivity primitive

- **Svelte 5:** `$state(value)` is a deeply reactive rune; reads in
  the template auto-track and re-render on mutation.
- **Svelte 4:** the `{ subscribe }` contract — any object with a
  `subscribe(set)` method that returns an unsubscribe function works as
  a store and is auto-tracked with the `$store` syntax.

## 2. Mapping

| Svelte                           | VMx                                  |
| -------------------------------- | ------------------------------------ |
| `$state(x)` / `writable(x)`      | `PropertyChangedMessage<T>` handler  |
| `on:click={fn}`                  | `command.execute(undefined)` in `fn` |
| `$derived(...)` / `derived(...)` | `DerivedProperty<T>` / `fromSources` |
| `onDestroy(() => cleanup)`       | dispose the subscription             |

## 3. Adapter skeleton — Svelte 4 store

```ts
// lib/vmStore.ts
import { readable, type Readable } from "svelte/store";
import { filter } from "rxjs/operators";
import { ComponentVMOf, IMessageHub, PropertyChangedMessage } from "@thekaveh/vmx";

export function vmStore<M, K extends keyof ComponentVMOf<M>>(
  vm: ComponentVMOf<M>,
  hub: IMessageHub<unknown>,
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
  export let vm: ComponentVMOf<Note>;
  export let hub: IMessageHub<unknown>;
  const model = vmStore(vm, hub, "model");
</script>

<h1>{$model.title}</h1>
<button on:click={() => vm.saveCommand.execute(undefined)}>Save</button>
```

For Svelte 5, drop the store wrapper and assign into a `$state(...)`
variable inside an `$effect(...)` that subscribes to the hub.

## 4. Fuller example

No worked Svelte Notes-Showcase ships yet. The React and Vue recipes
share the same hub-subscription shape.
