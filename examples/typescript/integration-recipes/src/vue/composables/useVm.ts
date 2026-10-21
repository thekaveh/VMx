// composables/useVm.ts
import {
  getCurrentInstance,
  getCurrentScope,
  onBeforeMount,
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
  const scope = getCurrentScope();
  if (!scope) {
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
    if (!scope.active) return;
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
  // Before the first render, subscribe just before it: a server render never
  // runs mount hooks, so SSR subscribes nothing.
  const instance = getCurrentInstance();
  if (instance && !instance.isMounted) onBeforeMount(start);
  else start();
  onScopeDispose(() => sub?.unsubscribe());
  return value;
}
