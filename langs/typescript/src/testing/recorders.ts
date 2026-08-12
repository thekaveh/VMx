import { Subscription } from "rxjs";
import type { ObservableList } from "../collections/observableList.js";
import {
  CollectionChangedMessage,
  type CollectionMutationAction,
} from "../messages/collectionChanged.js";
import { PropertyChangedMessage } from "../messages/propertyChanged.js";
import type { IMessageHub } from "../services/messageHub.js";

export interface PropertyChangeFilter<TSender> {
  readonly sender?: TSender;
  readonly propertyName?: string;
}

/** Records semantic PropertyChanged messages and owns its hub subscription. */
export class PropertyChangeRecorder<TSender = unknown> {
  readonly #records: PropertyChangedMessage<TSender>[] = [];
  readonly #subscription: Subscription;

  constructor(hub: IMessageHub, filter: PropertyChangeFilter<TSender> = {}) {
    this.#subscription = hub.messages.subscribe((message) => {
      if (!(message instanceof PropertyChangedMessage)) return;
      const typed = message as PropertyChangedMessage<TSender>;
      if (filter.sender !== undefined && typed.sender !== filter.sender) return;
      if (filter.propertyName !== undefined && typed.propertyName !== filter.propertyName) return;
      this.#records.push(typed);
    });
  }

  get records(): readonly PropertyChangedMessage<TSender>[] {
    return [...this.#records];
  }

  get propertyNames(): readonly string[] {
    return this.#records.map((record) => record.propertyName);
  }

  clear(): void {
    this.#records.length = 0;
  }

  dispose(): void {
    this.#subscription.unsubscribe();
  }
}

export function recordPropertyChanges<TSender = unknown>(
  hub: IMessageHub,
  filter: PropertyChangeFilter<TSender> = {},
): PropertyChangeRecorder<TSender> {
  return new PropertyChangeRecorder(hub, filter);
}

export interface CollectionChangeFilter {
  readonly sender?: object;
  readonly actions?: readonly CollectionMutationAction[];
}

/** Records serviced-collection messages and owns its hub subscription. */
export class CollectionChangeRecorder<T> {
  readonly #records: CollectionChangedMessage<T>[] = [];
  readonly #subscription: Subscription;

  constructor(hub: IMessageHub, filter: CollectionChangeFilter = {}) {
    this.#subscription = hub.messages.subscribe((message) => {
      if (!(message instanceof CollectionChangedMessage)) return;
      const typed = message as CollectionChangedMessage<T>;
      if (filter.sender !== undefined && typed.sender !== filter.sender) return;
      if (filter.actions !== undefined && !filter.actions.includes(typed.action)) return;
      this.#records.push(typed);
    });
  }

  get records(): readonly CollectionChangedMessage<T>[] {
    return [...this.#records];
  }

  get actions(): readonly CollectionMutationAction[] {
    return this.#records.map((record) => record.action);
  }

  clear(): void {
    this.#records.length = 0;
  }

  dispose(): void {
    this.#subscription.unsubscribe();
  }
}

export function recordCollectionChanges<T>(
  hub: IMessageHub,
  filter: CollectionChangeFilter = {},
): CollectionChangeRecorder<T> {
  return new CollectionChangeRecorder<T>(hub, filter);
}

export type ObservableListMutationAction = CollectionMutationAction;

export interface ObservableListChange<T> {
  readonly action: ObservableListMutationAction;
  readonly newItems: readonly T[];
  readonly oldItems: readonly T[];
  readonly newIndex: number;
  readonly oldIndex: number;
}

/** Records ObservableList's granular streams as one semantic ordered history. */
export class ObservableListRecorder<T> {
  readonly #records: ObservableListChange<T>[] = [];
  readonly #subscriptions = new Subscription();

  constructor(list: ObservableList<T>) {
    this.#subscriptions.add(list.itemAdded.subscribe(({ item, index }) => {
      this.#records.push({
        action: "add",
        newItems: [item],
        oldItems: [],
        newIndex: index,
        oldIndex: -1,
      });
    }));
    this.#subscriptions.add(list.itemRemoved.subscribe(({ item, index }) => {
      this.#records.push({
        action: "remove",
        newItems: [],
        oldItems: [item],
        newIndex: -1,
        oldIndex: index,
      });
    }));
    this.#subscriptions.add(list.itemReplaced.subscribe(({ newItem, oldItem, index }) => {
      this.#records.push({
        action: "replace",
        newItems: [newItem],
        oldItems: [oldItem],
        newIndex: index,
        oldIndex: index,
      });
    }));
    this.#subscriptions.add(list.reset.subscribe(() => {
      this.#records.push({
        action: "reset",
        newItems: [],
        oldItems: [],
        newIndex: -1,
        oldIndex: -1,
      });
    }));
  }

  get records(): readonly ObservableListChange<T>[] {
    return this.#records.map((record) => ({
      ...record,
      newItems: [...record.newItems],
      oldItems: [...record.oldItems],
    }));
  }

  clear(): void {
    this.#records.length = 0;
  }

  dispose(): void {
    this.#subscriptions.unsubscribe();
  }
}

export function recordObservableList<T>(list: ObservableList<T>): ObservableListRecorder<T> {
  return new ObservableListRecorder(list);
}
