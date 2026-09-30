# 9.9. Vue 3 Integration

Wire a `ComponentVMOf<M>` to a Vue 3 component via the Composition API
`reactive()` / `ref()` primitives.

## 9.9.1. Reactivity primitive

Vue 3's reactivity tracks reads and writes to `reactive(obj)` and
`ref()` values; templates re-render automatically when tracked
values change. Bridge VMx by syncing a local `ref` from VMx hub events.

## 9.9.2. Mapping

| Vue 3                             | VMx                                  |
| --------------------------------- | ------------------------------------ |
| `shallowRef` value + `triggerRef` | `PropertyChangedMessage<T>` handler  |
| `@click="fn"`                     | `command.execute()` in `fn`          |
| `computed(() => ...)`             | `DerivedProperty<T>` / `fromSources` |
| `onUnmounted(() => cleanup)`      | dispose the subscription             |

`republishModel()` announces a model that was mutated in place, so the
announced value is the same object the binding already holds. A plain `ref`
ignores assigning the same reference, so the composable stores the value in a
`shallowRef` and calls `triggerRef` on every matching message. A replacement
object or a scalar value re-renders the same way, and messages for another VM
or another property are filtered out.

## 9.9.3. Adapter skeleton

The composable and component below are the exact files run by
`examples/typescript/integration-recipes` against `vue` 3.5.43, including an
in-place mutation announced with `republishModel()`, replacement and scalar
updates, unrelated messages, and unmount cleanup.

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

No worked Vue Notes-Showcase ships yet. The React recipe
([react.md](react.md)) uses the same hub-subscription shape (just with
`useSyncExternalStore` instead of `ref`) and is a good reference.
