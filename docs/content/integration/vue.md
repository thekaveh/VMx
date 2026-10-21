# 9.9. Vue 3 Integration

Wire a `ComponentVMOf<M>` to a Vue 3 component through the Composition API
`shallowRef` and `triggerRef` primitives.

## 9.9.1. Reactivity primitive

Vue 3 tracks reads of a `shallowRef` value and re-renders the template when
that value changes. `triggerRef` forces the same re-render when the value keeps
its reference. The adapter updates a `shallowRef` from VMx hub messages. Each
message notifies watchers exactly once.

## 9.9.2. Mapping

| Vue 3                             | VMx                                  |
| --------------------------------- | ------------------------------------ |
| `shallowRef` value + `triggerRef` | `PropertyChangedMessage<T>` handler  |
| `@click="fn"`                     | `command.execute()` in `fn`          |
| `computed(() => ...)`             | `DerivedProperty<T>` / `fromSources` |
| `onMounted(start)`                | subscribe to the hub                 |
| `onScopeDispose(() => cleanup)`   | dispose the subscription             |

A [`republishModel()` announcement keeps the same reference](index.md#914-republished-models-keep-their-reference).
When a matching message leaves the reference unchanged, the composable calls
`triggerRef`. Otherwise it assigns the new value. A message for another VM or
another property is filtered out.

The composable has three rules:

- Call it inside `setup()` or an `effectScope`. Elsewhere it throws a
  `TypeError`, because no scope would release the subscription. Stopping the
  scope releases it.
- In a component, it subscribes when the component mounts. A server render
  never mounts, so it leaves no subscription.
- Hold view-models in `shallowRef` or `markRaw`. `ref()`, `reactive()` and
  `data()` wrap a VM in a proxy. The composable unwraps it with `toRaw`, but
  other code that reads a VM member through the proxy throws on VMx's
  `#private` fields.

## 9.9.3. Adapter skeleton

The composable and component below are the exact files run by
`examples/typescript/integration-recipes` against `vue` 3.5.43. The tests cover
an in-place mutation announced with `republishModel()`, replacement and scalar
updates, one synchronous watcher run per message, proxied view-models,
unrelated messages, unmount and effect-scope cleanup, and a server render.

<!-- checked-snippet: examples/typescript/integration-recipes/src/vue/composables/useVm.ts -->

```ts
// composables/useVm.ts
import {
  getCurrentInstance,
  getCurrentScope,
  onMounted,
  onScopeDispose,
  shallowRef,
  toRaw,
  triggerRef,
  type ShallowRef,
} from "vue";
import { filter, type Subscription } from "rxjs";
import { type ComponentVMOf, type IMessageHub, PropertyChangedMessage } from "@thekaveh/vmx";

/**
 * Binds one VM property for the lifetime of the calling component or effect
 * scope. `vm` and `hub` are fixed inputs: give the component a `:key` to rebind
 * it to another VM.
 */
export function useVm<M, K extends keyof ComponentVMOf<M>>(
  vm: ComponentVMOf<M>,
  hub: IMessageHub,
  property: K,
): Readonly<ShallowRef<ComponentVMOf<M>[K]>> {
  if (!getCurrentScope()) {
    throw new TypeError("useVm must be called inside setup() or an effect scope");
  }
  // A VM held in ref(), reactive() or data() arrives as a proxy. VMx reads
  // #private fields and hub messages carry the raw object, so bind the raw one.
  const raw = toRaw(vm);
  const messages = toRaw(hub).messages;
  let current = raw[property];
  const value = shallowRef(current) as ShallowRef<ComponentVMOf<M>[K]>;
  let sub: Subscription | undefined;
  const start = (): void => {
    current = raw[property];
    value.value = current;
    sub = messages
      .pipe(
        filter(
          (m): m is PropertyChangedMessage<unknown> =>
            m instanceof PropertyChangedMessage && m.sender === raw && m.propertyName === property,
        ),
      )
      .subscribe(() => {
        const next = raw[property];
        if (Object.is(next, current)) {
          // A republished model keeps its reference, so trigger explicitly.
          triggerRef(value);
        } else {
          current = next;
          value.value = next;
        }
      });
  };
  // Mounted hooks never run during a server render, so SSR subscribes nothing.
  if (getCurrentInstance()) onMounted(start);
  else start();
  onScopeDispose(() => sub?.unsubscribe());
  return value;
}
```

<!-- checked-snippet: examples/typescript/integration-recipes/src/vue/NoteView.vue -->

```vue
<script setup lang="ts">
import type { ComponentVMOf, ICommand, IMessageHub } from "@thekaveh/vmx";
import { useVm } from "./composables/useVm";
import type { Note } from "./note";

const props = defineProps<{
  vm: ComponentVMOf<Note>;
  hub: IMessageHub;
  saveCommand: ICommand;
}>();
const model = useVm(props.vm, props.hub, "model");
</script>

<template>
  <h1>{{ model.title }}</h1>
  <button @click="props.saveCommand.execute()">Save</button>
</template>
```

`vm` and `hub` are fixed for the binding's lifetime. To show a different VM,
re-create the component with a `:key` that identifies the VM, such as
`:key="vm.name"` when sibling names are unique.

## 9.9.4. Fuller example

There is no Vue Notes-Showcase. The runnable reference is
`examples/typescript/integration-recipes`. For a packaged adapter, see the
React recipe ([react.md](react.md)).
