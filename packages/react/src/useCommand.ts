import { useCallback } from "react";
import type { ICommand } from "@thekaveh/vmx";

import { useCanExecuteChanged, useCommandErrors } from "./internal/commandBinding.js";

export interface UseCommandResult {
  readonly canExecute: boolean;
  readonly execute: () => void;
}

export interface UseCommandOptions {
  /**
   * Called with each failure that the command sends on its `errors` channel
   * while the component is mounted. `AsyncRelayCommand.execute()` sends a
   * rejected task there, because no caller can receive it. A command with no
   * `errors` channel, such as `RelayCommand`, never calls it.
   */
  readonly onError?: (error: unknown) => void;
}

/** Bind a parameterless VMx command to React state and a stable callback. */
export function useCommand(command: ICommand, options?: UseCommandOptions): UseCommandResult {
  const getSnapshot = useCallback(() => command.canExecute(), [command]);
  const canExecute = useCanExecuteChanged(command, getSnapshot);
  const execute = useCallback(() => command.execute(), [command]);
  useCommandErrors(command, options?.onError);
  return { canExecute, execute };
}
