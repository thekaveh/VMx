/**
 * useCommand — React CommandBridge for a VMx `RelayCommand`.
 *
 * See scenario doc §7.1 (CommandBridge) and §7.3 (TS adapter signature) and
 * plan §4.c.
 *
 * Exposes a stable React handler that wraps `command.execute()` together with
 * the current `canExecute()` value. Subscribes once (via
 * `useSyncExternalStore`) to `command.canExecuteChanged` so any trigger-fed
 * predicate flip re-renders the binding component — the React analogue of the
 * Avalonia adapter's `RelayCommandBridge.CanExecuteChanged` re-raise (Phase
 * 4.a) and the Textual adapter's `bind_command` subscription (Phase 4.b).
 *
 * **VMx TS surface used**:
 *   - `RelayCommand.canExecute()` — *method*, not property (see
 *     `langs/typescript/src/commands/relayCommand.ts`).
 *   - `RelayCommand.canExecuteChanged` — rxjs `Observable<void>` emitting on
 *     every trigger.
 *
 * The returned `execute` is a fresh closure on each render. That is harmless:
 * React calls handlers eagerly and the underlying `cmd.execute()` already
 * gates on `canExecute()` (RelayCommand contract — see relayCommand.ts).
 */
import { useCallback, useSyncExternalStore } from "react";
import type { RelayCommand } from "vmx";

export interface UseCommandResult {
  readonly canExecute: boolean;
  execute(): void;
}

export function useCommand(cmd: RelayCommand): UseCommandResult {
  const subscribe = useCallback(
    (notify: () => void): (() => void) => {
      const subscription = cmd.canExecuteChanged.subscribe({
        next: () => notify(),
      });
      return () => subscription.unsubscribe();
    },
    [cmd],
  );

  // Snapshot is the live `canExecute()` reading. The RelayCommand contract
  // guarantees that two consecutive calls (without an intervening trigger
  // emission) return the same value, so useSyncExternalStore's strict-equality
  // comparison is stable between renders.
  const getSnapshot = useCallback(() => cmd.canExecute(), [cmd]);

  const canExecute = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const execute = useCallback(() => {
    cmd.execute();
  }, [cmd]);

  return { canExecute, execute };
}
