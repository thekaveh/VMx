/**
 * CollectionChangedMessage — published by ServicedObservableCollection to the hub
 * when the collection mutates.
 *
 * See spec/21-collections.md §2 and ADR-0024.
 */
import type { IMessage } from "./types.js";

/** Mutation action for a serviced collection message. */
export type CollectionMutationAction =
  | "add"
  | "remove"
  | "replace"
  | "move"
  | "reset";

export interface ICollectionChangedMessage<T> extends IMessage {
  readonly action: CollectionMutationAction;
  readonly newItems: readonly T[];
  readonly oldItems: readonly T[];
  readonly index: number;
  readonly oldIndex: number;
  readonly newIndex: number;
}

export class CollectionChangedMessage<T> implements ICollectionChangedMessage<T> {
  readonly sender: object;
  /** Derived from the sender's constructor name; no separate name field per spec §2.4. */
  get senderName(): string {
    return (this.sender as { constructor?: { name?: string } }).constructor?.name ?? "";
  }
  readonly action: CollectionMutationAction;
  readonly newItems: readonly T[];
  readonly oldItems: readonly T[];
  readonly index: number;
  readonly oldIndex: number;
  readonly newIndex: number;

  private constructor(
    sender: object,
    action: CollectionMutationAction,
    newItems: readonly T[],
    oldItems: readonly T[],
    index: number,
    oldIndex: number,
    newIndex: number,
  ) {
    this.sender = sender;
    this.action = action;
    this.newItems = newItems;
    this.oldItems = oldItems;
    this.index = index;
    this.oldIndex = oldIndex;
    this.newIndex = newIndex;
  }

  static forAdd<T>(
    sender: object,
    item: T,
    index: number,
  ): CollectionChangedMessage<T> {
    return new CollectionChangedMessage(
      sender,
      "add",
      [item],
      [],
      index,
      -1,
      index,
    );
  }

  static forRemove<T>(
    sender: object,
    item: T,
    index: number,
  ): CollectionChangedMessage<T> {
    return new CollectionChangedMessage(
      sender,
      "remove",
      [],
      [item],
      index,
      index,
      -1,
    );
  }

  static forReplace<T>(
    sender: object,
    newItem: T,
    oldItem: T,
    index: number,
  ): CollectionChangedMessage<T> {
    return new CollectionChangedMessage(
      sender,
      "replace",
      [newItem],
      [oldItem],
      index,
      index,
      index,
    );
  }

  static forMove<T>(
    sender: object,
    item: T,
    oldIndex: number,
    newIndex: number,
  ): CollectionChangedMessage<T> {
    return new CollectionChangedMessage(
      sender,
      "move",
      [item],
      [item],
      newIndex,
      oldIndex,
      newIndex,
    );
  }

  static forReset<T>(sender: object): CollectionChangedMessage<T> {
    return new CollectionChangedMessage(sender, "reset", [], [], -1, -1, -1);
  }
}
