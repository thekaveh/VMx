import { config, Observable, Subscriber, Subscription } from "rxjs";
import { describe, expect, it } from "vitest";
import {
  AggregateChangeReason,
  AggregateChangeStream,
  ComponentVM,
  ComponentVMOf,
  CompositeVM,
  GroupVM,
  KeyedServicedObservableCollection,
  MessageHub,
  RxDispatcher,
  ServicedObservableCollection,
} from "../../src/index.js";
import type {
  AggregateChange,
  ObservableMembershipSource,
} from "../../src/index.js";

class BodyError extends Error {}
class DeliveryError extends Error {}
class SelectorError extends Error {}
class SubscriptionError extends Error {}

class CountedChanges {
  subscribeCount = 0;
  unsubscribeCount = 0;
  emitOnSubscribe = false;
  readonly #subscribers: Subscriber<void>[] = [];

  readonly observable = new Observable<void>((subscriber) => {
    this.subscribeCount++;
    this.#subscribers.push(subscriber);
    if (this.emitOnSubscribe) subscriber.next();
    return () => {
      const index = this.#subscribers.indexOf(subscriber);
      if (index >= 0) this.#subscribers.splice(index, 1);
      this.unsubscribeCount++;
    };
  });

  emit(): void {
    for (const subscriber of [...this.#subscribers]) subscriber.next();
  }

  complete(): void {
    for (const subscriber of [...this.#subscribers]) subscriber.complete();
  }

  error(error: Error): void {
    for (const subscriber of [...this.#subscribers]) subscriber.error(error);
  }
}

class Item {
  readonly changes = new CountedChanges();
  disposeCount = 0;

  constructor(readonly name: string) {}

  dispose(): void {
    this.disposeCount++;
  }
}

class TestSource<T> implements ObservableMembershipSource<T> {
  readonly items: T[];
  readonly handlers: Array<() => void> = [];
  snapshotCount = 0;
  snapshotOverride: (() => readonly T[]) | null = null;

  constructor(...items: T[]) {
    this.items = [...items];
  }

  snapshot(): readonly T[] {
    this.snapshotCount++;
    return this.snapshotOverride?.() ?? [...this.items];
  }

  subscribeMembership(callback: () => void): Subscription {
    this.handlers.push(callback);
    return new Subscription(() => {
      const index = this.handlers.indexOf(callback);
      if (index >= 0) this.handlers.splice(index, 1);
    });
  }

  pulse(): void {
    for (const handler of [...this.handlers]) handler();
  }

  add(item: T): void {
    this.items.push(item);
    this.pulse();
  }

  remove(item: T): void {
    const index = this.items.indexOf(item);
    if (index >= 0) this.items.splice(index, 1);
    this.pulse();
  }

  move(fromIndex: number, toIndex: number): void {
    const [item] = this.items.splice(fromIndex, 1);
    if (item !== undefined) this.items.splice(toIndex, 0, item);
    this.pulse();
  }
}

function aggregate(source: ObservableMembershipSource<Item>): AggregateChangeStream<Item> {
  return new AggregateChangeStream(source, (item) => item.changes.observable);
}

function reasons(changes: readonly AggregateChange<Item>[]): AggregateChangeReason[] {
  return changes.map((change) => change.reason);
}

describe("AGCH-001", () => {
  it("delivers an atomic subscriber-local initial seed without replay", () => {
    const source = new TestSource(new Item("first"));
    const sut = aggregate(source);
    const plain: AggregateChange<Item>[] = [];
    const seeded: AggregateChange<Item>[] = [];
    sut.observe().subscribe((change) => plain.push(change));

    sut.observe({ emitInitial: true }).subscribe((change) => {
      seeded.push(change);
      if (change.reason === AggregateChangeReason.Initial) {
        source.add(new Item("racing"));
      }
    });

    expect(reasons(seeded)).toEqual([
      AggregateChangeReason.Initial,
      AggregateChangeReason.Membership,
    ]);
    expect(reasons(plain)).toEqual([AggregateChangeReason.Membership]);
    sut.dispose();
  });
});

describe("AGCH-002", () => {
  it("reconciles setup races and orders staged values behind membership", () => {
    const first = new Item("first");
    const raced = new Item("raced");
    const source = new TestSource(first);
    let raceOnce = true;
    source.snapshotOverride = () => {
      const snapshot = [...source.items];
      if (raceOnce) {
        raceOnce = false;
        source.items.push(raced);
        source.pulse();
      }
      return snapshot;
    };

    const sut = aggregate(source);
    expect(source.snapshotCount).toBe(2);
    expect(first.changes.subscribeCount).toBe(1);
    expect(raced.changes.subscribeCount).toBe(1);

    const observed: AggregateChange<Item>[] = [];
    sut.observe().subscribe((change) => observed.push(change));
    const synchronous = new Item("synchronous");
    synchronous.changes.emitOnSubscribe = true;
    source.add(synchronous);

    expect(reasons(observed)).toEqual([
      AggregateChangeReason.Membership,
      AggregateChangeReason.Item,
    ]);
    expect(observed[1]?.item).toBe(synchronous);
    sut.dispose();
  });
});

describe("AGCH-003", () => {
  it("emits the identical current item selected by a nested stream", () => {
    const item = new Item("nested");
    const sut = aggregate(new TestSource(item));
    const observed: AggregateChange<Item>[] = [];
    sut.observe().subscribe((change) => observed.push(change));

    item.changes.emit();

    expect(observed).toEqual([
      { reason: AggregateChangeReason.Item, item },
    ]);
    sut.dispose();
  });
});

describe("AGCH-004", () => {
  it("keeps completed and errored epochs silent until final removal and re-add", () => {
    const first = new Item("first");
    const second = new Item("second");
    const source = new ServicedObservableCollection<Item>();
    source.push(first);
    source.push(second);
    const sut = aggregate(source);
    const observed: AggregateChange<Item>[] = [];
    sut.observe().subscribe((change) => observed.push(change));

    first.changes.complete();
    second.changes.error(new Error("selected"));
    first.changes.emit();
    second.changes.emit();
    expect(observed).toEqual([]);

    source.move(0, 1);
    source.replaceAll([second, first]);
    source.push(first);
    expect(first.changes.subscribeCount).toBe(1);
    expect(second.changes.subscribeCount).toBe(1);

    source.remove(first);
    source.remove(first);
    source.push(first);
    expect(first.changes.subscribeCount).toBe(2);
    first.changes.emit();
    expect(observed.at(-1)?.item).toBe(first);
    sut.dispose();
  });
});

describe("AGCH-005", () => {
  it("transactionally rebuilds keyed Reset membership while retaining identity", () => {
    const first = new Item("first");
    const retained = new Item("retained");
    const added = new Item("added");
    const source = new KeyedServicedObservableCollection<string, Item>({
      keyOf: (item) => item.name,
    });
    source.push(first);
    source.push(retained);
    const sut = aggregate(source);
    const observed: AggregateChange<Item>[] = [];
    sut.observe().subscribe((change) => observed.push(change));

    source.replaceAll([retained, added]);

    expect(reasons(observed)).toEqual([AggregateChangeReason.Membership]);
    expect(first.changes.unsubscribeCount).toBe(1);
    expect(retained.changes.subscribeCount).toBe(1);
    expect(added.changes.subscribeCount).toBe(1);
    added.changes.emit();
    expect(observed.at(-1)?.item).toBe(added);
    sut.dispose();
  });
});

describe("AGCH-006", () => {
  it("refcounts duplicate object identities with one selected subscription", () => {
    const item = new Item("duplicate");
    const source = new TestSource(item, item);
    const sut = aggregate(source);
    const observed: AggregateChange<Item>[] = [];
    sut.observe().subscribe((change) => observed.push(change));

    expect(item.changes.subscribeCount).toBe(1);
    item.changes.emit();
    expect(reasons(observed)).toEqual([AggregateChangeReason.Item]);
    source.remove(item);
    expect(item.changes.unsubscribeCount).toBe(0);
    source.remove(item);
    expect(item.changes.unsubscribeCount).toBe(1);
    sut.dispose();
  });
});

describe("AGCH-007", () => {
  it("coalesces nested exceptional batches and preserves the body error", () => {
    const item = new Item("item");
    const source = new TestSource(item);
    const sut = aggregate(source);
    const observed: AggregateChange<Item>[] = [];
    sut.observe().subscribe((change) => observed.push(change));
    const bodyError = new BodyError("body");
    const deliveryError = new DeliveryError("delivery");
    class ThrowOnBatchSubscriber extends Subscriber<AggregateChange<Item>> {
      override next(change: AggregateChange<Item>): void {
        if (change.reason === AggregateChangeReason.Batch) throw deliveryError;
        super.next(change);
      }
    }
    sut.observe().subscribe(new ThrowOnBatchSubscriber());

    expect(() => {
      sut.withBatch(() => {
        item.changes.emit();
        sut.withBatch(() => source.add(new Item("added")));
        throw bodyError;
      });
    }).toThrow(bodyError);

    expect(reasons(observed)).toEqual([AggregateChangeReason.Batch]);

    expect(() => sut.withBatch(() => item.changes.emit())).toThrow(deliveryError);
    expect(reasons(observed)).toEqual([
      AggregateChangeReason.Batch,
      AggregateChangeReason.Batch,
    ]);

    item.changes.emit();
    expect(reasons(observed)).toEqual([
      AggregateChangeReason.Batch,
      AggregateChangeReason.Batch,
      AggregateChangeReason.Item,
    ]);
    sut.dispose();
  });
});

describe("AGCH-008", () => {
  it("keeps empty batches silent and Move subscription-stable", () => {
    const first = new Item("first");
    const second = new Item("second");
    const source = new ServicedObservableCollection<Item>();
    source.push(first);
    source.push(second);
    const sut = aggregate(source);
    const observed: AggregateChange<Item>[] = [];
    sut.observe().subscribe((change) => observed.push(change));

    sut.withBatch(() => undefined);
    expect(observed).toEqual([]);
    source.move(0, 1);
    expect(reasons(observed)).toEqual([AggregateChangeReason.Membership]);
    expect(first.changes.subscribeCount).toBe(1);
    expect(first.changes.unsubscribeCount).toBe(0);
    sut.dispose();

    const pendingItem = new Item("pending-item");
    const pendingSource = new TestSource(pendingItem);
    const pending = aggregate(pendingSource);
    const pendingObserved: AggregateChange<Item>[] = [];
    let runReentrantBatch = true;
    pending.observe().subscribe((change) => {
      pendingObserved.push(change);
      if (runReentrantBatch && change.reason === AggregateChangeReason.Item) {
        runReentrantBatch = false;
        pending.withBatch(() => pendingSource.add(new Item("pending-added")));
      }
    });
    pendingItem.changes.emit();
    expect(reasons(pendingObserved)).toEqual([
      AggregateChangeReason.Item,
      AggregateChangeReason.Batch,
    ]);
    pendingObserved.length = 0;
    pending.withBatch(() => undefined);
    expect(pendingObserved).toEqual([]);
    pending.dispose();

    const batchItem = new Item("batch-recipients");
    const batchSource = new TestSource(batchItem);
    const batch = aggregate(batchSource);
    const early: AggregateChange<Item>[] = [];
    const late: AggregateChange<Item>[] = [];
    const earlySubscription = batch
      .observe()
      .subscribe((change) => early.push(change));
    let lateSubscription: Subscription | undefined;
    batch.withBatch(() => {
      batchItem.changes.emit();
      lateSubscription = batch
        .observe()
        .subscribe((change) => late.push(change));
    });
    expect(reasons(early)).toEqual([AggregateChangeReason.Batch]);
    expect(late).toEqual([]);

    early.length = 0;
    late.length = 0;
    const joinedBeforeSecond: AggregateChange<Item>[] = [];
    let joinedBeforeSecondSubscription: Subscription | undefined;
    batch.withBatch(() => {
      batchItem.changes.emit();
      joinedBeforeSecondSubscription = batch
        .observe()
        .subscribe((change) => joinedBeforeSecond.push(change));
      batchItem.changes.emit();
    });
    expect(reasons(early)).toEqual([AggregateChangeReason.Batch]);
    expect(reasons(late)).toEqual([AggregateChangeReason.Batch]);
    expect(reasons(joinedBeforeSecond)).toEqual([AggregateChangeReason.Batch]);
    joinedBeforeSecondSubscription?.unsubscribe();

    early.length = 0;
    late.length = 0;
    batch.withBatch(() => {
      batchItem.changes.emit();
      earlySubscription.unsubscribe();
    });
    expect(early).toEqual([]);
    expect(reasons(late)).toEqual([AggregateChangeReason.Batch]);
    lateSubscription?.unsubscribe();
    batch.dispose();
  });
});

describe("AGCH-009", () => {
  it("serializes reentrant removal and rejects queued stale epoch work", () => {
    const item = new Item("item");
    const source = new TestSource(item);
    const sut = aggregate(source);
    const observed: AggregateChange<Item>[] = [];
    sut.observe().subscribe((change) => {
      observed.push(change);
      if (change.reason === AggregateChangeReason.Item && source.items.length > 0) {
        source.remove(item);
        item.changes.emit();
      }
    });

    item.changes.emit();
    expect(reasons(observed)).toEqual([
      AggregateChangeReason.Item,
      AggregateChangeReason.Membership,
    ]);
    source.add(item);
    expect(item.changes.subscribeCount).toBe(2);
    item.changes.emit();
    expect(observed.filter((change) => change.reason === AggregateChangeReason.Item)).toHaveLength(2);
    sut.dispose();
  });
});

describe("AGCH-010", () => {
  it("bounds failure, disposal, ownership, adapters, and observer effects", async () => {
    const nullSource = new TestSource(null as unknown as Item);
    expect(() => aggregate(nullSource)).toThrow(/null|undefined/i);
    expect(nullSource.handlers).toHaveLength(0);

    const valid = new Item("valid");
    const bad = new Item("bad");
    const constructionSource = new TestSource(valid, bad);
    expect(() => new AggregateChangeStream(constructionSource, (item) => {
      if (item === bad) throw new SelectorError("selector");
      return item.changes.observable;
    })).toThrow(SelectorError);
    expect(constructionSource.handlers).toHaveLength(0);
    expect(valid.changes.unsubscribeCount).toBe(1);

    const staged = new Item("staged");
    const subscribeBad = new Item("subscribe-bad");
    const subscriptionError = new SubscriptionError("subscribe");
    const subscriptionSource = new TestSource(staged, subscribeBad);
    const throwingSelected = {
      subscribe: () => { throw subscriptionError; },
    } as unknown as Observable<void>;
    expect(() => new AggregateChangeStream(subscriptionSource, (item) =>
      item === subscribeBad ? throwingSelected : item.changes.observable,
    )).toThrow(subscriptionError);
    expect(subscriptionSource.handlers).toHaveLength(0);
    expect(staged.changes.unsubscribeCount).toBe(1);

    const laterValid = new Item("later-valid");
    const laterBad = new Item("later-bad");
    const laterSource = new TestSource(laterValid);
    const later = new AggregateChangeStream(laterSource, (item) => {
      if (item === laterBad) throw new SelectorError("later selector");
      return item.changes.observable;
    });
    const errors: unknown[] = [];
    later.observe().subscribe({ error: (error) => errors.push(error) });
    laterSource.add(laterBad);
    expect(errors[0]).toBeInstanceOf(SelectorError);
    expect(laterSource.handlers).toHaveLength(0);
    expect(laterValid.changes.unsubscribeCount).toBe(1);
    later.dispose();

    const hub = new MessageHub();
    const dispatcher = RxDispatcher.immediate();
    const component = ComponentVMOf.builder<number>()
      .name("component")
      .services(hub, dispatcher)
      .model(1)
      .build();
    const components = new ServicedObservableCollection<ComponentVMOf<number>>();
    components.push(component);
    const componentAggregate = AggregateChangeStream.forComponents(components);
    const componentChanges: AggregateChange<ComponentVMOf<number>>[] = [];
    let completionCount = 0;
    componentAggregate.observe().subscribe({
      next: (change) => componentChanges.push(change),
      complete: () => completionCount++,
    });
    component.model = 2;
    expect(componentChanges.at(-1)).toEqual({
      reason: AggregateChangeReason.Item,
      item: component,
    });
    componentAggregate.dispose();
    componentAggregate.dispose();
    expect(completionCount).toBe(1);

    const composite = CompositeVM.builder<ComponentVM>()
      .name("composite")
      .services(hub, dispatcher)
      .children(() => [])
      .build();
    const group = GroupVM.builder<ComponentVM>()
      .name("group")
      .services(hub, dispatcher)
      .children(() => [])
      .build();
    const child = ComponentVM.builder().name("child").services(hub, dispatcher).build();
    const assertAdapter = (source: ObservableMembershipSource<ComponentVM> & {
      add(item: ComponentVM): void;
      remove(item: ComponentVM): boolean;
    }): void => {
      let pulses = 0;
      const subscription = source.subscribeMembership(() => pulses++);
      source.add(child);
      expect(source.snapshot()).toEqual([child]);
      source.remove(child);
      expect(pulses).toBe(2);
      subscription.unsubscribe();
    };
    assertAdapter(composite);
    assertAdapter(group);

    const owned = new Item("owned");
    const reentrantAdded = new Item("reentrant-added");
    const ownedSource = new TestSource(owned);
    const ownedAggregate = aggregate(ownedSource);
    const safe: AggregateChange<Item>[] = [];
    const late: AggregateChange<Item>[] = [];
    const unhandled: unknown[] = [];
    const previousUnhandled = config.onUnhandledError;
    config.onUnhandledError = (error) => unhandled.push(error);
    try {
      let throwOnce = true;
      ownedAggregate.observe().subscribe((change) => {
        if (!throwOnce || change.reason !== AggregateChangeReason.Item) return;
        throwOnce = false;
        ownedSource.add(reentrantAdded);
        ownedAggregate.observe({ emitInitial: true }).subscribe((lateChange) => {
          late.push(lateChange);
        });
        throw new Error("observer");
      });
      ownedAggregate.observe().subscribe((change) => safe.push(change));
      owned.changes.emit();
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(unhandled).toHaveLength(1);
      expect(reasons(safe)).toEqual([
        AggregateChangeReason.Item,
        AggregateChangeReason.Membership,
      ]);
      expect(reasons(late)).toEqual([AggregateChangeReason.Initial]);
      expect(owned.changes.unsubscribeCount).toBe(0);
      reentrantAdded.changes.emit();
      expect(safe.at(-1)?.item).toBe(reentrantAdded);
      expect(late.at(-1)?.item).toBe(reentrantAdded);
    } finally {
      config.onUnhandledError = previousUnhandled;
    }
    ownedAggregate.dispose();
    ownedAggregate.dispose();
    ownedSource.add(new Item("ignored"));
    expect(owned.disposeCount).toBe(0);
    expect(owned.changes.unsubscribeCount).toBe(1);
  });
});
