# 9.9. Vue 3 Integration

Wire a `ComponentVMOf<M>` to a Vue 3 component through the Composition API
`shallowRef` and `triggerRef` primitives.

## 9.9.1. Reactivity primitive

Vue 3 tracks reads of a `shallowRef` value and re-renders the template when
that value changes. `triggerRef` forces the same re-render when the value keeps
its reference. The adapter updates a `shallowRef` from VMx hub messages and
calls `triggerRef` on each one.

## 9.9.2. Mapping

| Vue 3                             | VMx                                  |
| --------------------------------- | ------------------------------------ |
| `shallowRef` value + `triggerRef` | `PropertyChangedMessage<T>` handler  |
| `@click="fn"`                     | `command.execute()` in `fn`          |
| `computed(() => ...)`             | `DerivedProperty<T>` / `fromSources` |
| `onUnmounted(() => cleanup)`      | dispose the subscription             |

A [`republishModel()` announcement keeps the same reference](index.md#914-republished-models-keep-their-reference),
so the composable calls `triggerRef` on every matching message. Messages for
another VM or another property are filtered out.

## 9.9.3. Adapter skeleton

The composable and component below are the exact files run by
`examples/typescript/integration-recipes` against `vue` 3.5.43, including an
in-place mutation announced with `republishModel()`, replacement and scalar
updates, unrelated messages, and unmount cleanup.

<!-- checked-snippet: examples/typescript/integration-recipes/src/vue/composables/useVm.ts -->

```ts
// composables/useVm.ts
import { onUnmounted, shallowRef, triggerRef, type ShallowRef } from "vue";
import { filter } from "rxjs";
import { type ComponentVMOf, type IMessageHub, PropertyChangedMessage } from "@thekaveh/vmx";

/**
 * Binds one VM property for the calling component's lifetime. `vm` and `hub`
 * are fixed inputs: give the component a `:key` to rebind it to another VM.
 */
export function useVm<M, K extends keyof ComponentVMOf<M>>(
  vm: ComponentVMOf<M>,
  hub: IMessageHub,
  property: K,
): Readonly<ShallowRef<ComponentVMOf<M>[K]>> {
  const value = shallowRef(vm[property]) as ShallowRef<ComponentVMOf<M>[K]>;
  const sub = hub.messages
    .pipe(
      filter(
        (m): m is PropertyChangedMessage<unknown> =>
          m instanceof PropertyChangedMessage && m.sender === vm && m.propertyName === property,
      ),
    )
    .subscribe(() => {
      value.value = vm[property];
      // A republished model keeps its reference, so trigger explicitly.
      triggerRef(value);
    });
  onUnmounted(() => sub.unsubscribe());
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
