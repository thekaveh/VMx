import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";
import type { ICommand } from "@thekaveh/vmx";

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

interface ErrorChannel {
  subscribe(observer: { next: (error: unknown) => void }): { unsubscribe(): void };
}

function errorChannelOf(command: ICommand): ErrorChannel | null {
  // ICommand declares no `errors` member, so detect the channel at run time.
  const errors = (command as { readonly errors?: unknown }).errors;
  return typeof errors === "object" && errors !== null &&
    typeof (errors as Partial<ErrorChannel>).subscribe === "function"
    ? errors as ErrorChannel
    : null;
}

/** Bind a parameterless VMx command to React state and a stable callback. */
export function useCommand(command: ICommand, options?: UseCommandOptions): UseCommandResult {
  const subscribe = useCallback(
    (notify: () => void): (() => void) => {
      // Disposal must re-render the binding, so a disposed command renders
      // as disabled. RelayCommand and the wrappers (DecoratorCommand,
      // CompositeCommand, ConfirmationDecoratorCommand) emit once when
      // disposed. AsyncRelayCommand only completes this stream, so re-read
      // canExecute on complete too.
      const subscription = command.canExecuteChanged.subscribe({
        next: notify,
        complete: notify,
      });
      return () => subscription.unsubscribe();
    },
    [command],
  );
  const getSnapshot = useCallback(() => command.canExecute(), [command]);
  const canExecute = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const execute = useCallback(() => command.execute(), [command]);

  // Keep the latest handler without resubscribing on every render.
  const onError = options?.onError;
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  });
  const observesErrors = onError !== undefined;
  useEffect(() => {
    if (!observesErrors) return undefined;
    const errors = errorChannelOf(command);
    if (errors === null) return undefined;
    const subscription = errors.subscribe({
      next: (error) => onErrorRef.current?.(error),
    });
    return () => subscription.unsubscribe();
  }, [command, observesErrors]);

  return { canExecute, execute };
}
