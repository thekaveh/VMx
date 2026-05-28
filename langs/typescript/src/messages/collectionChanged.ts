/**
 * CollectionChangedMessage — published by ServicedObservableCollection to the hub
 * when the collection mutates.
 *
 * See spec/21-collections.md §2 and ADR-0024.
 */
import type { IMessage } from "./types.js";

/** Mutation action for a serviced collection message. */
export type CollectionMutationAction = "add" | "remove" | "replace" | "reset";

export interface ICollectionChangedMessage<T> extends IMessage {
  readonly action: CollectionMutationAction;
  readonly newItems: readonly T[];
  readonly oldItems: readonly T[];
  readonly index: number;
}

export class CollectionChangedMessage<T> implements ICollectionChangedMessage<T> {
  readonly senderName: string;
  readonly senderObject: object;
  readonly action: CollectionMutationAction;
  readonly newItems: readonly T[];
  readonly oldItems: readonly T[];
  readonly index: number;

  private constructor(
    sender: object,
    senderName: string,
    action: CollectionMutationAction,
    newItems: readonly T[],
    oldItems: readonly T[],
    index: number,
  ) {
    this.senderObject = sender;
    this.senderName = senderName;
    this.action = action;
    this.newItems = newItems;
    this.oldItems = oldItems;
    this.index = index;
  }

  static forAdd<T>(
    sender: object,
    senderName: string,
    item: T,
    index: number,
  ): CollectionChangedMessage<T> {
    return new CollectionChangedMessage(sender, senderName, "add", [item], [], index);
  }

  static forRemove<T>(
    sender: object,
    senderName: string,
    item: T,
    index: number,
  ): CollectionChangedMessage<T> {
    return new CollectionChangedMessage(sender, senderName, "remove", [], [item], index);
  }

  static forReplace<T>(
    sender: object,
    senderName: string,
    newItem: T,
    oldItem: T,
    index: number,
  ): CollectionChangedMessage<T> {
    return new CollectionChangedMessage(
      sender,
      senderName,
      "replace",
      [newItem],
      [oldItem],
      index,
    );
  }

  static forReset<T>(sender: object, senderName: string): CollectionChangedMessage<T> {
    return new CollectionChangedMessage(sender, senderName, "reset", [], [], -1);
  }
}
