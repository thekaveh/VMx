import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";
import type { ICommand } from "@thekaveh/vmx";

interface ErrorChannel {
  subscribe(observer: { next: (error: unknown) => void }): { unsubscribe(): void };
}

function errorChannelOf(command: object): ErrorChannel | null {
  // ICommand declares no `errors` member, so detect the channel at run time.
  const errors = (command as { readonly errors?: unknown }).errors;
  return typeof errors === "object" && errors !== null &&
    typeof (errors as Partial<ErrorChannel>).subscribe === "function"
    ? errors as ErrorChannel
    : null;
}

/**
 * Re-read `readCanExecute` on every `canExecuteChanged` notification. Shared by
 * `useCommand` and `useParameterizedCommand`, so both observe a command the
 * same way.
 */
export function useCanExecuteChanged(
  command: Pick<ICommand, "canExecuteChanged">,
  readCanExecute: () => boolean,
): boolean {
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
  return useSyncExternalStore(subscribe, readCanExecute, readCanExecute);
}

/**
 * Forward each failure on the command's `errors` channel to the latest
 * `onError` while the component is mounted. A command without an `errors`
 * channel, such as `RelayCommand`, never calls `onError`.
 */
export function useCommandErrors(
  command: object,
  onError: ((error: unknown) => void) | undefined,
): void {
  // Keep the latest handler without resubscribing on every render.
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
}
