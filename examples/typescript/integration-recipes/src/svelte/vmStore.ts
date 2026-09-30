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
