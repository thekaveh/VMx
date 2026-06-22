// Unit tests for ServicedObservableCollection<T>.
// Conformance-level tests live in tests/conformance/col-001-to-004-serviced.test.ts.

import { describe, it, expect } from "vitest";
import { MessageHub } from "../../src/services/messageHub.js";
import { ServicedObservableCollection } from "../../src/collections/servicedObservableCollection.js";
import { CollectionChangedMessage } from "../../src/messages/collectionChanged.js";

// ---------------------------------------------------------------------------
// Null-hub fallback
// ---------------------------------------------------------------------------

describe("ServicedObservableCollection – null-hub fallback", () => {
  it("push emits local event without error when no hub is present", () => {
    const sut = new ServicedObservableCollection<string>();
    const events: CollectionChangedMessage<string>[] = [];
    sut.collectionChanged.subscribe((e) => events.push(e));

    sut.push("hello");

    expect(events).toHaveLength(1);
    expect(events[0]?.action).toBe("add");
    expect(events[0]?.newItems).toEqual(["hello"]);
  });

  it("clear emits reset without error when no hub is present", () => {
    const sut = new ServicedObservableCollection<number>();
    sut.push(1);
    sut.push(2);
    const events: CollectionChangedMessage<number>[] = [];
    sut.collectionChanged.subscribe((e) => events.push(e));

    sut.clear();

    expect(events).toHaveLength(1);
    expect(events[0]?.action).toBe("reset");
  });

  it("all mutations complete without throwing when no hub is present", () => {
    const sut = new ServicedObservableCollection<number>();
    expect(() => {
      sut.push(1);
      sut.push(2);
      sut.splice(0, 1);
      sut.setAt(0, 99);
      sut.clear();
    }).not.toThrow();
  });

  it("setAt rejects negative and out-of-range indices", () => {
    const sut = new ServicedObservableCollection<number>();
    sut.push(1);
    expect(() => sut.setAt(-1, 99)).toThrow(RangeError);
    expect(() => sut.setAt(1, 99)).toThrow(RangeError);
  });
});

// ---------------------------------------------------------------------------
// Hub wiring
// ---------------------------------------------------------------------------

describe("ServicedObservableCollection – hub wiring", () => {
  it("push publishes add message to hub", () => {
    const hub = new MessageHub();
    const sut = new ServicedObservableCollection<string>(hub);
    const msgs: unknown[] = [];
    hub.messages.subscribe((m) => msgs.push(m));

    sut.push("x");

    expect(msgs).toHaveLength(1);
    const m = msgs[0] as CollectionChangedMessage<string>;
    expect(m.action).toBe("add");
    expect(m.newItems).toEqual(["x"]);
    expect(m.index).toBe(0);
  });

  it("pop publishes remove message to hub", () => {
    const hub = new MessageHub();
    const sut = new ServicedObservableCollection<string>(hub);
    sut.push("y");

    const msgs: CollectionChangedMessage<string>[] = [];
    hub.messages.subscribe((m) => msgs.push(m as CollectionChangedMessage<string>));
    sut.pop();

    expect(msgs).toHaveLength(1);
    expect(msgs[0]?.action).toBe("remove");
    expect(msgs[0]?.oldItems).toEqual(["y"]);
  });

  it("setAt publishes replace message to hub", () => {
    const hub = new MessageHub();
    const sut = new ServicedObservableCollection<string>(hub);
    sut.push("old");

    const msgs: CollectionChangedMessage<string>[] = [];
    hub.messages.subscribe((m) => msgs.push(m as CollectionChangedMessage<string>));
    sut.setAt(0, "new");

    expect(msgs).toHaveLength(1);
    expect(msgs[0]?.action).toBe("replace");
    expect(msgs[0]?.newItems).toEqual(["new"]);
    expect(msgs[0]?.oldItems).toEqual(["old"]);
  });

  it("clear publishes reset message to hub", () => {
    const hub = new MessageHub();
    const sut = new ServicedObservableCollection<string>(hub);
    sut.push("a");

    const msgs: CollectionChangedMessage<string>[] = [];
    hub.messages.subscribe((m) => msgs.push(m as CollectionChangedMessage<string>));
    sut.clear();

    expect(msgs).toHaveLength(1);
    expect(msgs[0]?.action).toBe("reset");
    expect(msgs[0]?.newItems).toEqual([]);
    expect(msgs[0]?.oldItems).toEqual([]);
    expect(msgs[0]?.index).toBe(-1);
  });

  it("both local and hub observers see the change", () => {
    const hub = new MessageHub();
    const sut = new ServicedObservableCollection<number>(hub);
    let localSaw = false;
    let hubSaw = false;
    sut.collectionChanged.subscribe(() => { localSaw = true; });
    hub.messages.subscribe(() => { hubSaw = true; });

    sut.push(42);

    expect(localSaw).toBe(true);
    expect(hubSaw).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Large-N stress
// ---------------------------------------------------------------------------

describe("ServicedObservableCollection – stress", () => {
  it("10k pushes + clear completes without error", () => {
    const hub = new MessageHub();
    const sut = new ServicedObservableCollection<number>(hub);
    let hubCount = 0;
    hub.messages.subscribe(() => hubCount++);

    const n = 10_000;
    for (let i = 0; i < n; i++) sut.push(i);
    sut.clear();

    expect(sut.length).toBe(0);
    expect(hubCount).toBe(n + 1); // n adds + 1 reset
  });
});

// ---------------------------------------------------------------------------
// Iterable + at()
// ---------------------------------------------------------------------------

describe("ServicedObservableCollection – indexing", () => {
  it("at() returns item at index", () => {
    const sut = new ServicedObservableCollection<number>();
    sut.push(10);
    sut.push(20);
    expect(sut.at(0)).toBe(10);
    expect(sut.at(1)).toBe(20);
  });

  it("toArray() returns a copy of items", () => {
    const sut = new ServicedObservableCollection<number>();
    sut.push(1);
    sut.push(2);
    const arr = sut.toArray();
    expect(arr).toEqual([1, 2]);
    // mutation of copy does not affect sut
    arr.push(3);
    expect(sut.length).toBe(2);
  });

  it("is iterable", () => {
    const sut = new ServicedObservableCollection<number>();
    sut.push(1);
    sut.push(2);
    expect([...sut]).toEqual([1, 2]);
  });
});

// ---------------------------------------------------------------------------
// No-op splice (spec/21 §2.4 — messages are emitted per mutation)
// ---------------------------------------------------------------------------

describe("ServicedObservableCollection – no-op splice", () => {
  it("emits nothing when the splice removes and inserts nothing", () => {
    const sut = new ServicedObservableCollection<number>();
    sut.push(1);
    const events: CollectionChangedMessage<number>[] = [];
    sut.collectionChanged.subscribe((e) => events.push(e));

    const removed = sut.splice(0, 0);

    expect(removed).toEqual([]);
    expect(events).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// splice with a negative start resolves the emitted index (spec/21 line 148:
// the Remove carries the actual removal position, not the raw argument).
// ---------------------------------------------------------------------------

describe("ServicedObservableCollection – negative-index splice", () => {
  it("emits the resolved removal index for splice(-1, 1)", () => {
    const sut = new ServicedObservableCollection<string>();
    sut.push("a");
    sut.push("b");
    sut.push("c");
    const events: CollectionChangedMessage<string>[] = [];
    sut.collectionChanged.subscribe((e) => events.push(e));

    const removed = sut.splice(-1, 1);

    expect(removed).toEqual(["c"]);
    expect(events).toHaveLength(1);
    expect(events[0]?.action).toBe("remove");
    expect(events[0]?.oldItems).toEqual(["c"]);
    // index must be the resolved position (2), not the raw -1.
    expect(events[0]?.index).toBe(2);
  });
});
