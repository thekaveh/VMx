/**
 * The selection-input scope of the Select and Deselect notification (ADR-0242).
 *
 * A container membership transaction, and an aggregate slot replacement, open
 * the scope. While it is open, a child whose selection inputs changed (its
 * IsCurrent flag or its Parent link) is queued, not notified. The outermost
 * scope emits the queue after the container has finished its membership change,
 * so no `canExecuteChanged` subscriber runs inside that change (spec/06 §4.3).
 */

let depth = 0;
let pending: Array<() => void> = [];

/** Opens a scope. Pair each call with `leaveSelectionScope`. */
export function enterSelectionScope(): void {
  depth += 1;
}

/**
 * Closes a scope. The outermost close emits the queued notifications. A failing
 * subscriber does not skip the others; the first failure is rethrown.
 */
export function leaveSelectionScope(): void {
  if (depth > 0) depth -= 1;
  if (depth > 0) return;
  const queued = pending;
  pending = [];
  let failed = false;
  let firstError: unknown;
  for (const emit of queued) {
    try {
      emit();
    } catch (error) {
      if (!failed) {
        failed = true;
        firstError = error;
      }
    }
  }
  if (failed) throw firstError;
}

/** Queues a notification for the open scope, or runs it at once when no scope is open. */
export function queueSelectionInputs(emit: () => void): void {
  if (depth === 0) {
    emit();
    return;
  }
  pending.push(emit);
}

/** Runs `body` inside a selection-input scope. */
export function withSelectionScope<T>(body: () => T): T {
  enterSelectionScope();
  try {
    return body();
  } finally {
    leaveSelectionScope();
  }
}
