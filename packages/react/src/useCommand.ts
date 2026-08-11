import { useCallback, useSyncExternalStore } from "react";
import type { ICommand } from "@thekaveh/vmx";

export interface UseCommandResult {
  readonly canExecute: boolean;
  readonly execute: () => void;
}

/** Bind a parameterless VMx command to React state and a stable callback. */
export function useCommand(command: ICommand): UseCommandResult {
  const subscribe = useCallback(
    (notify: () => void): (() => void) => {
      const subscription = command.canExecuteChanged.subscribe({ next: notify });
      return () => subscription.unsubscribe();
    },
    [command],
  );
  const getSnapshot = useCallback(() => command.canExecute(), [command]);
  const canExecute = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const execute = useCallback(() => command.execute(), [command]);
  return { canExecute, execute };
}
