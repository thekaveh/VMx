import { useCallback } from "react";
import type { ICommandOf } from "@thekaveh/vmx";

import { useCanExecuteChanged, useCommandErrors } from "./internal/commandBinding.js";
import type { UseCommandOptions, UseCommandResult } from "./useCommand.js";

/**
 * Bind a VMx command that takes a parameter, such as `ICommandOf<T>`, to React
 * state and a callback. `canExecute` re-reads `canExecute(parameter)` on
 * `canExecuteChanged` and whenever `parameter` changes. `execute` runs the
 * command with the bound parameter. `options.onError` behaves as in
 * `useCommand`.
 *
 * The parameter is a separate argument, so `useCommand` keeps its signature.
 * A new parameter reference also gives a new `execute` callback.
 */
export function useParameterizedCommand<T>(
  command: ICommandOf<T>,
  parameter: T,
  options?: UseCommandOptions,
): UseCommandResult {
  const getSnapshot = useCallback(() => command.canExecute(parameter), [command, parameter]);
  const canExecute = useCanExecuteChanged(command, getSnapshot);
  const execute = useCallback(() => command.execute(parameter), [command, parameter]);
  useCommandErrors(command, options?.onError);
  return { canExecute, execute };
}
