import { useCallback } from "react";
import { PropertyChangedMessage, type IMessageHub } from "@thekaveh/vmx";

import { useVersionedSelector, type Equality } from "./internal/useVersionedSelector.js";

export interface HubBackedValue {
  readonly hub: IMessageHub;
}

export function useVm<TVm extends object & HubBackedValue>(vm: TVm): TVm;
export function useVm<TVm extends object & HubBackedValue, TSelected>(
  vm: TVm,
  selector: (vm: TVm) => TSelected,
  equality?: Equality<TSelected>,
): TSelected;
export function useVm<TVm extends object & HubBackedValue, TSelected>(
  vm: TVm,
  selector?: (vm: TVm) => TSelected,
  equality?: Equality<TSelected>,
): TVm | TSelected {
  const sourceSubscribe = useCallback(
    (invalidate: () => void): (() => void) => {
      const subscription = vm.hub.messages.subscribe({
        next: (message) => {
          if (message instanceof PropertyChangedMessage && message.sender === vm) {
            invalidate();
          }
        },
      });
      return () => subscription.unsubscribe();
    },
    [vm],
  );

  const selected = useVersionedSelector(
    sourceSubscribe,
    (version) => selector === undefined ? version : selector(vm),
    selector === undefined ? Object.is : (equality ?? Object.is),
    selector === undefined,
  );
  return selector === undefined ? vm : selected as TSelected;
}
