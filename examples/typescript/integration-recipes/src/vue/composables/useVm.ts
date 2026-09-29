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
