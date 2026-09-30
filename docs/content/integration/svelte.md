# 9.10. Svelte Integration

Wire a `ComponentVMOf<M>` to a Svelte component through a custom store, which
works on Svelte 4 and 5, or through Svelte 5 runes (`$props`, `$derived`,
`$effect`).

## 9.10.1. Reactivity primitive

- **Store:** any object with a `subscribe(run)` method that returns an
  unsubscribe function is a store, and `$store` in a component subscribes to
  it for the component's lifetime. `readable(initial, start)` runs `start` for
  the first subscriber and its cleanup after the last, and keeps the last value
  in between.
- **Runes (Svelte 5):** `$derived` recomputes when the state it reads changes,
  and an `$effect` re-runs, after its returned cleanup, when the state it reads
  changes. Cleanup also runs when the component is destroyed.

## 9.10.2. Mapping

| Svelte                                 | VMx                                  |
| -------------------------------------- | ------------------------------------ |
| store `set(...)` / `$derived` override | `PropertyChangedMessage<T>` handler  |
| `on:click` / `onclick`                 | `command.execute()` in the handler   |
| `derived(...)` / `$derived(...)`       | `DerivedProperty<T>` / `fromSources` |
| store stop function / `$effect` return | dispose the hub subscription         |

The view owns only its hub subscription. Whoever created the VM constructs and
disposes it; neither adapter changes the VM's lifecycle. Both adapters observe
properties announced with `PropertyChangedMessage`. Lifecycle status arrives as
`ConstructionStatusChangedMessage` and needs its own filter.

`republishModel()` announces a model that was mutated in place, so the
announced value is the same object the view already holds. A store's `set`
always notifies for objects, and the runes component wraps each value in a new
object, so both render the mutation.

## 9.10.3. Adapter skeleton — store (Svelte 4 and 5)

The store and component below are the exact files run by
`examples/typescript/integration-recipes` against `svelte` 5.57.1. The store
uses only the `svelte/store` contract that Svelte 4 shares.

```ts
// vmStore.ts
import { readable, type Readable } from "svelte/store";
import { filter } from "rxjs";
import { type ComponentVMOf, type IMessageHub, PropertyChangedMessage } from "@thekaveh/vmx";

/**
 * A store for one VM property. Svelte runs the start function for the first
 * subscriber and its cleanup after the last, so every subscriber shares one
 * hub subscription, and each (re)connection re-reads the VM to pick up
 * changes made while the store had no subscribers.
 */
export function vmStore<M, K extends keyof ComponentVMOf<M>>(
  vm: ComponentVMOf<M>,
  hub: IMessageHub,
  property: K,
): Readable<ComponentVMOf<M>[K]> {
  return readable(vm[property], (set) => {
    const subscription = hub.messages
      .pipe(
        filter(
          (m): m is PropertyChangedMessage<unknown> =>
            m instanceof PropertyChangedMessage && m.sender === vm && m.propertyName === property,
        ),
      )
      .subscribe(() => set(vm[property]));
    try {
      // Read after subscribing, so a change in between is not lost.
      set(vm[property]);
    } catch (error) {
      subscription.unsubscribe();
      throw error;
    }
    return () => subscription.unsubscribe();
  });
}
```

```svelte
<script lang="ts">
  import type { ComponentVMOf, ICommand, IMessageHub } from "@thekaveh/vmx";
  import type { Note } from "./note";
  import { vmStore } from "./vmStore";

  export let vm: ComponentVMOf<Note>;
  export let hub: IMessageHub;
  export let saveCommand: ICommand;

  // A new vm or hub creates a new store; `$model` moves to it and releases
  // the old one.
  $: model = vmStore(vm, hub, "model");
</script>

<h1>{$model.title}</h1>
<button on:click={() => saveCommand.execute()}>Save</button>
```

Attachment order matters. `start` subscribes to the hub first and then reads
the VM, so a change made at any point before or during attachment is delivered
with the first value. All subscribers share the one hub subscription; the last
unsubscribe releases it. Because Svelte keeps the old value while nobody is
subscribed, the next subscriber gets a fresh read instead of that stale value.

## 9.10.4. Adapter skeleton — Svelte 5 runes

The same fixture mounts this component with changing inputs:

```svelte
<script lang="ts">
  import { filter } from "rxjs";
  import {
    PropertyChangedMessage,
    type ComponentVMOf,
    type ICommand,
    type IMessageHub,
  } from "@thekaveh/vmx";
  import type { Note } from "./note";

  interface Props {
    vm: ComponentVMOf<Note>;
    hub: IMessageHub;
    saveCommand: ICommand;
  }

  const { vm, hub, saveCommand }: Props = $props();

  // A fresh box per update: a republished model keeps its reference.
  let note = $derived({ model: vm.model });

  $effect(() => {
    // Reading `vm` and `hub` here re-runs the effect, after its cleanup,
    // whenever either input changes.
    const source = vm;
    const subscription = hub.messages
      .pipe(
        filter(
          (m) =>
            m instanceof PropertyChangedMessage &&
            m.sender === source &&
            m.propertyName === "model",
        ),
      )
      .subscribe(() => {
        note = { model: source.model };
      });
    // Catch up with changes made between the render and the subscription.
    note = { model: source.model };
    return () => subscription.unsubscribe();
  });
</script>

<h1>{note.model.title}</h1>
<button onclick={() => saveCommand.execute()}>Save</button>
```

`note` recomputes whenever `vm` changes, and the effect overrides it on each
matching message. The effect reads `vm` and `hub`, so a
new VM or hub runs the cleanup, which unsubscribes from the old hub, and then
subscribes to the new one. Its catch-up assignment covers changes made between
the render and the subscription.

## 9.10.5. Failures and disposed sources

- **Setup failure:** if the hub stream cannot be subscribed, or the store's
  catch-up read throws, the error propagates out of `subscribe` (the store) or
  out of mounting (both components). The store releases a hub subscription it
  has already made before rethrowing, so no listener remains. After a setup
  failure, discard the store: Svelte keeps the failed subscriber registered
  and will not call `start` again.
- **Hub error:** the adapters do not handle errors from `hub.messages`. RxJS
  ends the subscription and reports the error through `config.onUnhandledError`
  (by default it is rethrown asynchronously). The view keeps its last value;
  the store subscribes again on its next connection.
- **Disposed hub:** `MessageHub.dispose()` completes `messages`, which ends the
  subscription. The view keeps its last value.
- **Disposed VM:** a disposed VM publishes nothing and ignores assignments. The
  view keeps showing the retained model, and a reconnecting store reads that
  model. Destroying the component still releases the subscription.

## 9.10.6. Fuller example

No worked Svelte Notes-Showcase ships yet. The React and Vue recipes
share the same hub-subscription shape.
