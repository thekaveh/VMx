/**
 * CollectionChangedEvent — immutable payload emitted on collection mutations.
 *
 * Mirrors WPF's NotifyCollectionChangedEventArgs shape.
 * Action is one of "add" | "remove" | "move" | "reset".
 */
export type CollectionChangedAction = "add" | "remove" | "move" | "reset";

export interface CollectionChangedEvent {
  readonly action: CollectionChangedAction;
  readonly newItems: readonly unknown[];
  readonly newIndex: number;
  readonly oldItems: readonly unknown[];
  readonly oldIndex: number;
}

export function makeCollectionChangedEvent(
  action: CollectionChangedAction,
  opts?: {
    newItems?: readonly unknown[];
    newIndex?: number;
    oldItems?: readonly unknown[];
    oldIndex?: number;
  },
): CollectionChangedEvent {
  return {
    action,
    newItems: opts?.newItems ?? [],
    newIndex: opts?.newIndex ?? -1,
    oldItems: opts?.oldItems ?? [],
    oldIndex: opts?.oldIndex ?? -1,
  };
}
