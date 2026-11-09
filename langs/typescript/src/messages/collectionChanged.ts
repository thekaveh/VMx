/**
 * CollectionChangedMessage — published to the hub when a collection mutates, by
 * ServicedObservableCollection, KeyedServicedObservableCollection,
 * ObservableDictionary and, with the container as sender, by CompositeVM and
 * GroupVM after each local collection change.
 *
 * A CompositeVM or GroupVM message carries the container's name as its sender
 * name. Other senders default to their runtime type name (ADR-0194).
 *
 * See spec/21-collections.md §2, spec/01-concepts.md §1.4, ADR-0024 and ADR-0142.
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
  /**
   * Source position when supplied. Optional only so pre-v3.16 third-party
   * structural implementations remain assignable; VMx messages always set it.
   */
  readonly oldIndex?: number;
  /**
   * Destination position when supplied. Optional only so pre-v3.16 third-party
   * structural implementations remain assignable; VMx messages always set it.
   */
  readonly newIndex?: number;
}

export class CollectionChangedMessage<T> implements ICollectionChangedMessage<T> {
  readonly sender: object;
  /**
   * The diagnostic sender name: the container's name for a CompositeVM or
   * GroupVM message, else the sender's runtime type name (spec/21 §2.4,
   * ADR-0194).
   */
  readonly senderName: string;
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
    senderName: string | undefined,
  ) {
    this.sender = sender;
    this.senderName = senderName ?? typeName(sender);
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
    senderName?: string,
  ): CollectionChangedMessage<T> {
    return new CollectionChangedMessage(
      sender,
      "add",
      [item],
      [],
      index,
      -1,
      index,
      senderName,
    );
  }

  static forRemove<T>(
    sender: object,
    item: T,
    index: number,
    senderName?: string,
  ): CollectionChangedMessage<T> {
    return new CollectionChangedMessage(
      sender,
      "remove",
      [],
      [item],
      index,
      index,
      -1,
      senderName,
    );
  }

  static forReplace<T>(
    sender: object,
    newItem: T,
    oldItem: T,
    index: number,
    senderName?: string,
  ): CollectionChangedMessage<T> {
    return new CollectionChangedMessage(
      sender,
      "replace",
      [newItem],
      [oldItem],
      index,
      index,
      index,
      senderName,
    );
  }

  static forMove<T>(
    sender: object,
    item: T,
    oldIndex: number,
    newIndex: number,
    senderName?: string,
  ): CollectionChangedMessage<T> {
    return new CollectionChangedMessage(
      sender,
      "move",
      [item],
      [item],
      newIndex,
      oldIndex,
      newIndex,
      senderName,
    );
  }

  static forReset<T>(
    sender: object,
    senderName?: string,
  ): CollectionChangedMessage<T> {
    return new CollectionChangedMessage(
      sender,
      "reset",
      [],
      [],
      -1,
      -1,
      -1,
      senderName,
    );
  }
}

/** The sender's runtime type name, or "" when it has none. */
function typeName(sender: object): string {
  return (sender as { constructor?: { name?: string } }).constructor?.name ?? "";
}
