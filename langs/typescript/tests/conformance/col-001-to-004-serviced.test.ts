// Conformance tests: COL-001..COL-004 — ServicedObservableCollection<T>.
// See spec/21-collections.md §2 and ADR-0024.

import { describe, it, expect } from "vitest";
import { MessageHub } from "../../src/services/messageHub.js";
import { ServicedObservableCollection } from "../../src/collections/servicedObservableCollection.js";
import { CollectionChangedMessage } from "../../src/messages/collectionChanged.js";

// ---------------------------------------------------------------------------
// COL-001
// ---------------------------------------------------------------------------

describe("COL-001", () => {
  it("ServicedObservableCollection publishes to hub after local CollectionChanged on add", () => {
    const hub = new MessageHub();
    const sut = new ServicedObservableCollection<string>(hub);

    const localEvents: CollectionChangedMessage<string>[] = [];
    const hubMessages: unknown[] = [];
    // Shared order log: the local CollectionChanged event MUST fire before the
    // hub message is published (spec/21 §2; parity with Python/C#).
    const callOrder: string[] = [];

    sut.collectionChanged.subscribe((e) => {
      localEvents.push(e);
      callOrder.push("local");
    });
    hub.messages.subscribe((m) => {
      hubMessages.push(m);
      callOrder.push("hub");
    });

    sut.push("alpha");

    // Local-before-hub ordering
    expect(callOrder).toEqual(["local", "hub"]);

    // Local event
    expect(localEvents).toHaveLength(1);
    expect(localEvents[0]?.action).toBe("add");
    expect(localEvents[0]?.newItems).toEqual(["alpha"]);
    expect(localEvents[0]?.index).toBe(0);

    // Hub message
    expect(hubMessages).toHaveLength(1);
    const msg = hubMessages[0];
    expect(msg).toBeInstanceOf(CollectionChangedMessage);
    const cm = msg as CollectionChangedMessage<string>;
    expect(cm.action).toBe("add");
    expect(cm.newItems).toEqual(["alpha"]);
    expect(cm.index).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// COL-002
// ---------------------------------------------------------------------------

describe("COL-002", () => {
  it("ServicedObservableCollection publishes correct messages on remove and replace", () => {
    const hub = new MessageHub();
    const sut = new ServicedObservableCollection<string>(hub);
    sut.push("a");
    sut.push("b");

    const localEvents: CollectionChangedMessage<string>[] = [];
    const hubMessages: CollectionChangedMessage<string>[] = [];
    sut.collectionChanged.subscribe((e) => localEvents.push(e));
    hub.messages.subscribe((m) => hubMessages.push(m as CollectionChangedMessage<string>));

    // ── Remove ──────────────────────────────────────────────────────────────
    sut.splice(0, 1); // remove "a"

    expect(localEvents).toHaveLength(1);
    expect(localEvents[0]?.action).toBe("remove");
    expect(localEvents[0]?.oldItems).toEqual(["a"]);

    expect(hubMessages).toHaveLength(1);
    expect(hubMessages[0]?.action).toBe("remove");
    expect(hubMessages[0]?.oldItems).toEqual(["a"]);

    // ── Replace ─────────────────────────────────────────────────────────────
    localEvents.length = 0;
    hubMessages.length = 0;

    sut.setAt(0, "b_replaced");

    expect(localEvents).toHaveLength(1);
    expect(localEvents[0]?.action).toBe("replace");
    expect(localEvents[0]?.newItems).toEqual(["b_replaced"]);
    expect(localEvents[0]?.oldItems).toEqual(["b"]);

    expect(hubMessages).toHaveLength(1);
    expect(hubMessages[0]?.action).toBe("replace");
    expect(hubMessages[0]?.newItems).toEqual(["b_replaced"]);
    expect(hubMessages[0]?.oldItems).toEqual(["b"]);
  });
});

// ---------------------------------------------------------------------------
// COL-003
// ---------------------------------------------------------------------------

describe("COL-003", () => {
  it("Null-hub fallback: no hub means no publication, no error on any mutation", () => {
    const sut = new ServicedObservableCollection<number>(); // no hub

    const localEvents: CollectionChangedMessage<number>[] = [];
    sut.collectionChanged.subscribe((e) => localEvents.push(e));

    // All mutations must not throw
    sut.push(1);
    sut.push(2);
    sut.splice(0, 1); // remove
    sut.setAt(0, 99); // replace
    sut.clear();

    // Local events fired for each of the 5 mutations
    expect(localEvents).toHaveLength(5);
  });
});

// ---------------------------------------------------------------------------
// COL-004
// ---------------------------------------------------------------------------

describe("COL-004", () => {
  it("ServicedObservableCollection fires hub message on the caller thread without marshaling", () => {
    // In JavaScript / Node.js there is only one thread per event-loop context.
    // "Same-thread" means the hub handler runs synchronously inside push(),
    // i.e. before push() returns — no micro/macrotask deferral.
    const hub = new MessageHub();
    const sut = new ServicedObservableCollection<number>(hub);

    const callOrder: string[] = [];

    hub.messages.subscribe(() => callOrder.push("hub"));
    sut.push(42);
    callOrder.push("after-push");

    // hub handler must have run BEFORE we reach "after-push"
    expect(callOrder).toEqual(["hub", "after-push"]);
  });
});
