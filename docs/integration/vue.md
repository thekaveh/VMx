# Vue 3 integration

Wire a `ComponentVMOf<M>` to a Vue 3 component via the Composition API
`reactive()` / `ref()` primitives.

## 1. Reactivity primitive

Vue 3's reactivity tracks reads and writes to `reactive(obj)` and
`ref()` values; templates re-render automatically when tracked
values change. Bridge VMx by syncing a local `ref` from VMx hub events.

## 2. Mapping

| Vue 3                         | VMx                                  |
| ----------------------------- | ------------------------------------ |
| `ref(value).value = newValue` | `PropertyChangedMessage<T>` handler  |
| `@click="fn"`                 | `command.execute()` in `fn`          |
| `computed(() => ...)`         | `DerivedProperty<T>` / `fromSources` |
| `onUnmounted(() => cleanup)`  | dispose the subscription             |

## 3. Adapter skeleton

```ts
// composables/useVm.ts
import { ref, onUnmounted, type Ref } from "vue";
import { filter } from "rxjs/operators";
import { ComponentVMOf, type IMessageHub, PropertyChangedMessage } from "@thekaveh/vmx";

export function useVm<M, K extends keyof ComponentVMOf<M>>(
  vm: ComponentVMOf<M>,
  hub: IMessageHub,
  property: K
): Ref<ComponentVMOf<M>[K]> {
  const value = ref(vm[property]) as Ref<ComponentVMOf<M>[K]>;
  const sub = hub.messages
    .pipe(filter((m): m is PropertyChangedMessage<unknown> =>
      m instanceof PropertyChangedMessage &&
      m.sender === vm &&
      m.propertyName === property))
    .subscribe(() => { value.value = vm[property]; });
  onUnmounted(() => sub.unsubscribe());
  return value;
}
```

```vue
<script setup lang="ts">
import { useVm } from "./composables/useVm";
const props = defineProps<{ vm: ComponentVMOf<Note>; hub: IMessageHub }>();
const model = useVm(props.vm, props.hub, "model");
</script>

<template>
  <h1>{{ model.title }}</h1>
  <button @click="vm.saveCommand.execute()">Save</button>
</template>
```

## 4. Fuller example

No worked Vue Notes-Showcase ships yet. The React recipe
([react.md](react.md)) uses the same hub-subscription shape (just with
`useSyncExternalStore` instead of `ref`) and is a good reference.
