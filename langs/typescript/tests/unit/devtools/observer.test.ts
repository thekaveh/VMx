import { describe, expect, it } from "vitest";
import { MessageHub } from "../../../src/services/messageHub.js";
import { PropertyChangedMessage } from "../../../src/messages/propertyChanged.js";
import { CollectionChangedMessage } from "../../../src/messages/collectionChanged.js";
import {
  observeHub,
  type DevtoolsErrorContext,
  type DevtoolsEvent,
  type DevtoolsTimerScheduler,
} from "../../../src/devtools/index.js";

class ManualTimerScheduler implements DevtoolsTimerScheduler {
  readonly #pending = new Set<() => void>();

  get size(): number {
    return this.#pending.size;
  }

  schedule(callback: () => void, _delayMs: number): unknown {
    this.#pending.add(callback);
    return callback;
  }

  cancel(handle: unknown): void {
    this.#pending.delete(handle as () => void);
  }

  flush(): void {
    const callbacks = [...this.#pending];
    this.#pending.clear();
    callbacks.forEach((callback) => callback());
  }
}

describe("observeHub", () => {
  it("maps delivered messages to safe stable metadata and explicit named snapshots", () => {
    const hub = new MessageHub();
    const sender = { privateToken: "must-not-leak" };
    const events: DevtoolsEvent[] = [];
    let selected = 0;
    const connection = observeHub(hub, (event) => events.push(event), {
      name: "daydreams",
      now: () => 42,
      snapshots: [
        { name: "app", select: () => ({ route: "gallery", selected: ++selected }) },
      ],
    });

    hub.send(PropertyChangedMessage.create(sender, "AppVM", "route"));
    hub.send(CollectionChangedMessage.forAdd(sender, { secret: "item" }, 3));

    expect(events).toEqual([
      {
        name: "daydreams",
        timestamp: 42,
        action: {
          type: "PropertyChangedMessage/AppVM/route",
          messageType: "PropertyChangedMessage",
          senderName: "AppVM",
          sequence: 1,
          details: { propertyName: "route" },
        },
        state: { app: { route: "gallery", selected: 1 } },
      },
      {
        name: "daydreams",
        timestamp: 42,
        action: {
          type: "CollectionChangedMessage/Object/add",
          messageType: "CollectionChangedMessage",
          senderName: "Object",
          sequence: 2,
          details: { action: "add", index: 3, oldIndex: -1, newIndex: 3 },
        },
        state: { app: { route: "gallery", selected: 2 } },
      },
    ]);
    expect(JSON.stringify(events)).not.toContain("must-not-leak");
    expect(JSON.stringify(events)).not.toContain("item");
    connection.dispose();
  });

  it("filters before sampling and applies action/state redaction", () => {
    const hub = new MessageHub();
    const events: DevtoolsEvent[] = [];
    const connection = observeHub(hub, (event) => events.push(event), {
      allow: (message) => message.senderName !== "Denied",
      deny: (message) => message.senderName === "AlsoDenied",
      redact: (value, context) => context.kind === "action"
        ? { ...(value as object), senderName: "[redacted]" }
        : { safe: (value as { safe: string }).safe },
      snapshots: [
        { name: "session", select: () => ({ safe: "visible", token: "private" }) },
      ],
    });

    hub.send(PropertyChangedMessage.create({}, "Denied", "x"));
    hub.send(PropertyChangedMessage.create({}, "AlsoDenied", "x"));
    hub.send(PropertyChangedMessage.create({}, "Allowed", "x"));

    expect(events).toHaveLength(1);
    expect(events[0]?.action.senderName).toBe("[redacted]");
    expect(events[0]?.state).toEqual({ session: { safe: "visible" } });
    connection.dispose();
  });

  it("bounds and sanitizes circular, private, and unsupported snapshot values", () => {
    const hub = new MessageHub();
    const events: DevtoolsEvent[] = [];
    const circular: Record<string, unknown> = {
      text: "abcdef",
      big: 9n,
      fn: () => undefined,
      symbol: Symbol("private"),
      array: [1, 2, 3],
      nested: { keep: { stop: true } },
      ignored: "too-many-keys",
    };
    circular.self = circular;
    Object.defineProperty(circular, "throwing", {
      enumerable: true,
      get: () => { throw new Error("private getter"); },
    });

    const connection = observeHub(hub, (event) => events.push(event), {
      limits: { maxDepth: 2, maxStringLength: 3, maxArrayLength: 2, maxObjectKeys: 7 },
      snapshots: [{ name: "complex", select: () => circular }],
    });
    hub.send(PropertyChangedMessage.create({}, "VM", "model"));

    expect(events[0]?.state).toEqual({
      complex: {
        text: "abc…",
        big: "9n",
        fn: "[function]",
        symbol: "[symbol]",
        array: [1, 2, "[1 more]"],
        nested: { keep: "[max depth]" },
        ignored: "too…",
        "…": "[2 more keys]",
      },
    });
    connection.dispose();
  });

  it("marks circular references and throwing getters without reading through them", () => {
    const hub = new MessageHub();
    const events: DevtoolsEvent[] = [];
    const value: Record<string, unknown> = {};
    value.self = value;
    Object.defineProperty(value, "private", {
      enumerable: true,
      get: () => { throw new Error("must stay isolated"); },
    });
    const connection = observeHub(hub, (event) => events.push(event), {
      snapshots: [{ name: "state", select: () => value }],
    });

    hub.send(PropertyChangedMessage.create({}, "VM", "model"));

    expect(events[0]?.state).toEqual({
      state: { self: "[circular]", private: "[unavailable]" },
    });
    connection.dispose();
  });

  it("isolates clock and hostile metadata access failures", () => {
    const hub = new MessageHub();
    const events: DevtoolsEvent[] = [];
    const errors: DevtoolsErrorContext[] = [];
    const connection = observeHub(hub, (event) => events.push(event), {
      now: () => { throw new Error("clock failed"); },
      onError: (_error, context) => errors.push(context),
    });
    const hostile = new Proxy({ sender: {} }, {
      get: (target, key, receiver) => {
        if (key === "senderName") throw new Error("private sender name");
        return Reflect.get(target, key, receiver) as unknown;
      },
    });

    expect(() => hub.send(hostile as never)).not.toThrow();

    expect(events).toEqual([]);
    expect(errors).toEqual([{ phase: "clock", sequence: 1 }]);
    connection.dispose();
  });

  it("falls back safely when structural message prototype inspection throws", () => {
    const hub = new MessageHub();
    const events: DevtoolsEvent[] = [];
    const connection = observeHub(hub, (event) => events.push(event));
    const hostile = new Proxy({ sender: {}, senderName: "Hostile" }, {
      getPrototypeOf: () => { throw new Error("prototype access escaped"); },
    });

    hub.send(hostile);

    expect(events).toHaveLength(1);
    expect(events[0]?.action).toMatchObject({
      messageType: "Object",
      senderName: "Hostile",
      sequence: 1,
    });
    connection.dispose();
  });

  it("preserves reserved consumer snapshot names as own JSON state properties", () => {
    const hub = new MessageHub();
    const events: DevtoolsEvent[] = [];
    const connection = observeHub(hub, (event) => events.push(event), {
      snapshots: [{ name: "__proto__", select: () => ({ route: "gallery" }) }],
    });

    hub.send(PropertyChangedMessage.create({}, "VM", "model"));

    expect(Object.prototype.hasOwnProperty.call(events[0]?.state ?? {}, "__proto__")).toBe(true);
    expect(JSON.stringify(events[0]?.state)).toBe('{"__proto__":{"route":"gallery"}}');
    connection.dispose();
  });

  it("isolates mapper, selector, serializer, redactor, and sink failures", () => {
    const hub = new MessageHub();
    const delivered: DevtoolsEvent[] = [];
    const errors: Array<{ message: string; context: DevtoolsErrorContext }> = [];
    let invocation = 0;
    const connection = observeHub(hub, (event) => {
      if (event.action.sequence === 5) throw new Error("sink failed");
      delivered.push(event);
    }, {
      mapAction: (message, fallback) => {
        if (message.senderName === "mapper") throw new Error("mapper failed");
        return fallback;
      },
      snapshots: [
        {
          name: "state",
          select: () => {
            invocation += 1;
            if (invocation === 1) throw new Error("selector failed");
            return invocation;
          },
          serialize: (value) => {
            if (value === 2) throw new Error("serializer failed");
            return value;
          },
        },
      ],
      redact: (value, context) => {
        if (context.sequence === 4) throw new Error("redactor failed");
        return value;
      },
      onError: (error, context) => errors.push({
        message: (error as Error).message,
        context,
      }),
    });

    for (const senderName of ["mapper", "selector", "serializer", "redactor", "sink", "later"]) {
      hub.send(PropertyChangedMessage.create({}, senderName, "value"));
    }

    expect(delivered.map((event) => event.action.sequence)).toEqual([6]);
    expect(errors.map(({ message }) => message)).toEqual([
      "mapper failed",
      "selector failed",
      "serializer failed",
      "redactor failed",
      "sink failed",
    ]);
    expect(errors.map(({ context }) => context.phase)).toEqual([
      "map-action",
      "select-snapshot",
      "serialize-snapshot",
      "redact",
      "sink",
    ]);
    connection.dispose();
  });

  it("samples every Nth post-filter message while preserving accepted sequence", () => {
    const hub = new MessageHub();
    const events: DevtoolsEvent[] = [];
    const connection = observeHub(hub, (event) => events.push(event), {
      allow: (message) => message.senderName !== "denied",
      sampleEvery: 2,
    });

    hub.send(PropertyChangedMessage.create({}, "denied", "ignored"));
    for (const senderName of ["one", "two", "three", "four"]) {
      hub.send(PropertyChangedMessage.create({}, senderName, "value"));
    }

    expect(events.map((event) => [event.action.sequence, event.action.senderName]))
      .toEqual([[2, "two"], [4, "four"]]);
    connection.dispose();
  });

  it("normalizes non-finite and non-positive sampling/throttle options", () => {
    const hub = new MessageHub();
    const timer = new ManualTimerScheduler();
    const events: DevtoolsEvent[] = [];
    const connection = observeHub(hub, (event) => events.push(event), {
      sampleEvery: Number.NaN,
      throttleMs: Number.POSITIVE_INFINITY,
      timerScheduler: timer,
    });

    hub.send(PropertyChangedMessage.create({}, "VM", "model"));

    expect(events).toHaveLength(1);
    expect(timer.size).toBe(0);
    connection.dispose();
  });

  it("preserves the required action envelope under extreme serialization limits", () => {
    const hub = new MessageHub();
    const events: DevtoolsEvent[] = [];
    const connection = observeHub(hub, (event) => events.push(event), {
      limits: { maxDepth: 0, maxObjectKeys: 1, maxStringLength: 4 },
    });

    hub.send(PropertyChangedMessage.create({}, "PrivateVM", "privateProperty"));

    expect(events[0]?.action).toEqual({
      type: "Prop…",
      messageType: "Prop…",
      senderName: "Priv…",
      sequence: 1,
    });
    connection.dispose();
  });

  it("coalesces a high-frequency hub batch and snapshots once at flush", () => {
    const hub = new MessageHub();
    const timer = new ManualTimerScheduler();
    const events: DevtoolsEvent[] = [];
    let selections = 0;
    const connection = observeHub(hub, (event) => events.push(event), {
      name: "world",
      throttleMs: 10,
      timerScheduler: timer,
      snapshots: [{ name: "world", select: () => ({ selections: ++selections }) }],
    });

    hub.batch(() => {
      hub.send(PropertyChangedMessage.create({}, "WorldVM", "cells"));
      hub.send(PropertyChangedMessage.create({}, "WorldVM", "camera"));
      hub.send(PropertyChangedMessage.create({}, "WorldVM", "route"));
    });

    expect(events).toEqual([]);
    expect(selections).toBe(0);
    expect(timer.size).toBe(1);
    timer.flush();

    expect(events).toHaveLength(1);
    expect(events[0]?.action).toMatchObject({
      type: "VMx batch/world/3",
      messageType: "VMxBatch",
      senderName: "world",
      sequence: 3,
      details: { count: 3 },
    });
    expect(events[0]?.action.details?.actions).toEqual([
      expect.objectContaining({ senderName: "WorldVM", sequence: 1 }),
      expect.objectContaining({ senderName: "WorldVM", sequence: 2 }),
      expect.objectContaining({ senderName: "WorldVM", sequence: 3 }),
    ]);
    expect(events[0]?.state).toEqual({ world: { selections: 1 } });
    connection.dispose();
  });

  it("retains bounded action details while counting a much larger throttled burst", () => {
    const hub = new MessageHub();
    const timer = new ManualTimerScheduler();
    const events: DevtoolsEvent[] = [];
    const connection = observeHub(hub, (event) => events.push(event), {
      throttleMs: 1,
      timerScheduler: timer,
      limits: { maxArrayLength: 3 },
    });

    for (let index = 0; index < 1_000; index++) {
      hub.send(PropertyChangedMessage.create({}, `VM-${String(index)}`, "model"));
    }
    timer.flush();

    expect(events[0]?.action).toMatchObject({
      type: "VMx batch/VMx/1000",
      sequence: 1_000,
      details: { count: 1_000, retainedCount: 3, omittedCount: 997 },
    });
    expect(events[0]?.action.details?.actions).toEqual([
      expect.objectContaining({ sequence: 1 }),
      expect.objectContaining({ sequence: 2 }),
      expect.objectContaining({ sequence: 3 }),
    ]);
    connection.dispose();
  });

  it("supports a scheduler that flushes synchronously without stalling later events", () => {
    const hub = new MessageHub();
    const events: DevtoolsEvent[] = [];
    const scheduler: DevtoolsTimerScheduler = {
      schedule: (callback) => {
        callback();
        return undefined;
      },
      cancel: () => undefined,
    };
    const connection = observeHub(hub, (event) => events.push(event), {
      throttleMs: 1,
      timerScheduler: scheduler,
    });

    hub.send(PropertyChangedMessage.create({}, "first", "model"));
    hub.send(PropertyChangedMessage.create({}, "second", "model"));

    expect(events.map((event) => event.action.sequence)).toEqual([1, 2]);
    connection.dispose();
  });

  it("preserves reentrant hub order and owns completion deterministically", () => {
    const hub = new MessageHub();
    const timer = new ManualTimerScheduler();
    const events: DevtoolsEvent[] = [];
    let completed = 0;
    const connection = observeHub(hub, {
      next: (event) => events.push(event),
      complete: () => completed++,
    }, { throttleMs: 1, timerScheduler: timer });
    const reentrant = hub.messages.subscribe((message) => {
      if (message.senderName === "first") {
        hub.send(PropertyChangedMessage.create({}, "second", "value"));
      }
    });

    hub.send(PropertyChangedMessage.create({}, "first", "value"));
    hub.dispose();
    timer.flush();

    expect(events).toEqual([]);
    expect(timer.size).toBe(0);
    expect(completed).toBe(1);
    connection.dispose();
    connection.dispose();
    reentrant.unsubscribe();
  });

  it("cancels pending work and becomes inert after idempotent disposal", () => {
    const hub = new MessageHub();
    const timer = new ManualTimerScheduler();
    const events: DevtoolsEvent[] = [];
    let selections = 0;
    const connection = observeHub(hub, (event) => events.push(event), {
      throttleMs: 1,
      timerScheduler: timer,
      snapshots: [{ name: "state", select: () => ++selections }],
    });

    hub.send(PropertyChangedMessage.create({}, "before", "value"));
    connection.dispose();
    connection.dispose();
    hub.send(PropertyChangedMessage.create({}, "after", "value"));
    timer.flush();

    expect(timer.size).toBe(0);
    expect(selections).toBe(0);
    expect(events).toEqual([]);
    hub.dispose();
  });

  it("keeps concurrent hubs independent and reconnects with a fresh sequence", () => {
    const firstHub = new MessageHub();
    const secondHub = new MessageHub();
    const firstEvents: DevtoolsEvent[] = [];
    const secondEvents: DevtoolsEvent[] = [];
    const first = observeHub(firstHub, (event) => firstEvents.push(event));
    const second = observeHub(secondHub, (event) => secondEvents.push(event));

    firstHub.send(PropertyChangedMessage.create({}, "first", "value"));
    secondHub.send(PropertyChangedMessage.create({}, "second", "value"));
    first.dispose();
    const reconnected = observeHub(firstHub, (event) => firstEvents.push(event));
    firstHub.send(PropertyChangedMessage.create({}, "reconnected", "value"));

    expect(firstEvents.map((event) => event.action.sequence)).toEqual([1, 1]);
    expect(secondEvents.map((event) => event.action.sequence)).toEqual([1]);
    reconnected.dispose();
    second.dispose();
    firstHub.dispose();
    secondHub.dispose();
  });
});
