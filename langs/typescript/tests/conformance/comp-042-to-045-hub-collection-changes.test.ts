/**
 * Containers publish their collection changes on the hub
 * (spec ch. 01 §1.4, ch. 06 §4, ch. 07, ADR-0142).
 */
import { describe, expect, it } from "vitest";
import {
  CollectionChangedMessage,
  ComponentVM,
  ComponentVMBase,
  CompositeVM,
  ForwardingCompositeVM,
  GroupVM,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";
import type { CollectionChangedEvent } from "../../src/index.js";

const dispatcher = RxDispatcher.immediate();

function child(hub: MessageHub, name: string): ComponentVM {
  return ComponentVM.builder().name(name).services(hub, dispatcher).build();
}

function composite(hub: MessageHub, name = "composite") {
  return CompositeVM.builder<ComponentVMBase>()
    .name(name).services(hub, dispatcher).children(() => []).build();
}

function group(hub: MessageHub, name = "group") {
  return GroupVM.builder<ComponentVMBase>()
    .name(name).services(hub, dispatcher).children(() => []).build();
}

function hubMessages(hub: MessageHub): CollectionChangedMessage<unknown>[] {
  const messages: CollectionChangedMessage<unknown>[] = [];
  hub.messages.subscribe((message) => {
    if (message instanceof CollectionChangedMessage) messages.push(message);
  });
  return messages;
}

interface Observable {
  readonly collectionChanged: { subscribe(next: (event: CollectionChangedEvent) => void): unknown };
}

/** One log of local events and hub messages from `container`, in delivery order. */
function interleaved(hub: MessageHub, container: Observable): string[] {
  const log: string[] = [];
  container.collectionChanged.subscribe((event) => {
    log.push(`local:${event.action}:${event.oldIndex}:${event.newIndex}`);
  });
  hub.messages.subscribe((message) => {
    if (message instanceof CollectionChangedMessage && message.sender === container) {
      log.push(`hub:${message.action}:${message.oldIndex}:${message.newIndex}`);
    }
  });
  return log;
}

function expectHubFollowsEachLocalEvent(log: string[], localEvents: number): void {
  expect(log).toHaveLength(localEvents * 2);
  for (let i = 0; i < log.length; i += 2) {
    expect(log[i]).toMatch(/^local:/);
    expect(log[i + 1]).toBe(log[i]?.replace(/^local:/, "hub:"));
  }
}

describe("COMP-042", () => {
  it("publishes one hub message after each local event, sent by the composite", () => {
    const hub = new MessageHub();
    const parent = composite(hub);
    const [a, b, c, d] = ["a", "b", "c", "d"].map((name) => child(hub, name)) as [
      ComponentVM, ComponentVM, ComponentVM, ComponentVM,
    ];
    const log = interleaved(hub, parent);
    const messages = hubMessages(hub);

    parent.add(a);
    parent.insert(0, b);
    parent.move(0, 1);
    parent.setAt(0, c);
    parent.removeAt(1);
    parent.remove(c);
    parent.add(d);
    parent.clear();

    expectHubFollowsEachLocalEvent(log, 9);
    expect(messages.every((message) => message.sender === parent)).toBe(true);
    expect(messages.map((message) => message.action)).toEqual([
      "add", "add", "move", "remove", "add", "remove", "remove", "add", "reset",
    ]);
    expect(messages[0]?.newItems).toEqual([a]);
    expect(messages[2]?.newItems).toEqual([b]);
    expect(messages[3]?.oldItems).toEqual([a]);
    expect(messages[4]?.newItems).toEqual([c]);
  });

  it("delivers the hub message after the membership is committed", () => {
    const hub = new MessageHub();
    const parent = composite(hub);
    const a = child(hub, "a");
    const seen: boolean[] = [];
    hub.messages.subscribe((message) => {
      if (message instanceof CollectionChangedMessage) seen.push(parent.snapshot().includes(a));
    });

    parent.add(a);
    parent.remove(a);

    expect(seen).toEqual([true, false]);
  });
});

describe("COMP-043", () => {
  it("publishes nothing inside a batch and one Reset after the local Reset", () => {
    const hub = new MessageHub();
    const parent = composite(hub);
    const log = interleaved(hub, parent);

    const outer = parent.batchUpdate();
    parent.add(child(hub, "a"));
    const inner = parent.batchUpdate();
    parent.add(child(hub, "b"));
    parent.move(0, 1);
    inner.dispose();
    expect(log).toEqual([]);
    outer.dispose();

    expect(log).toEqual(["local:reset:-1:-1", "hub:reset:-1:-1"]);
  });

  it("publishes nothing for an empty batch or one holding only a same-index move", () => {
    const hub = new MessageHub();
    const parent = composite(hub);
    parent.add(child(hub, "a"));
    const messages = hubMessages(hub);

    parent.batchUpdate().dispose();
    const batch = parent.batchUpdate();
    parent.move(0, 0);
    batch.dispose();

    expect(messages).toEqual([]);
  });
});

describe("COMP-044", () => {
  it("publishes the old Remove before the new Add on a transfer", () => {
    const hub = new MessageHub();
    const oldParent = composite(hub, "old");
    const newParent = group(hub, "new");
    const moved = child(hub, "moved");
    oldParent.add(moved);
    const messages = hubMessages(hub);

    newParent.add(moved);

    expect(messages.map((message) => [message.sender, message.action])).toEqual([
      [oldParent, "remove"],
      [newParent, "add"],
    ]);
  });

  it("publishes nothing for rejected, rolled-back, or same-index mutations", () => {
    const hub = new MessageHub();
    const parent = composite(hub);
    const outer = composite(hub, "outer");
    const a = child(hub, "a");
    parent.add(a);
    outer.add(parent);
    const source = composite(hub, "source");
    const failing = ComponentVM.builder().name("failing").services(hub, dispatcher)
      .onConstruct(() => { throw new Error("construct failed"); }).build();
    source.add(failing);
    const destination = CompositeVM.builder<ComponentVMBase>()
      .name("destination").services(hub, dispatcher).children(() => [])
      .autoConstructOnAdd(true).build();
    destination.construct();
    const messages = hubMessages(hub);

    expect(() => parent.add(a)).toThrow();
    expect(() => parent.add(outer)).toThrow();
    expect(() => parent.insert(99, child(hub, "late"))).toThrow();
    expect(() => destination.add(failing)).toThrow("construct failed");
    parent.move(0, 0);

    expect(source.snapshot()).toContain(failing);
    expect(messages).toEqual([]);
  });
});

describe("COMP-045", () => {
  it("defers messages inside a hub transaction and keeps their order", () => {
    const hub = new MessageHub();
    const parent = composite(hub);
    const messages = hubMessages(hub);

    hub.batch(() => {
      parent.add(child(hub, "a"));
      parent.add(child(hub, "b"));
      expect(messages).toEqual([]);
    });

    expect(messages.map((message) => [message.action, message.newIndex])).toEqual([
      ["add", 0],
      ["add", 1],
    ]);
  });

  it("publishes nothing once the composite is disposed", () => {
    const hub = new MessageHub();
    const parent = composite(hub);
    parent.add(child(hub, "a"));
    const messages = hubMessages(hub);

    parent.dispose();
    try {
      parent.add(child(hub, "late"));
    } catch {
      // A disposed container may reject the mutation; either way it publishes nothing.
    }

    expect(messages.filter((message) => message.sender === parent)).toEqual([]);
  });

  it("publishes each change once through a forwarding wrapper, sent by the wrapped composite", () => {
    const hub = new MessageHub();
    const parent = composite(hub);
    const wrapper = new ForwardingCompositeVM(parent);
    const messages = hubMessages(hub);

    wrapper.add(child(hub, "a"));

    expect(messages).toHaveLength(1);
    expect(messages[0]?.sender).toBe(parent);
  });
});

describe("GRP-012", () => {
  it("publishes one hub message after each local event, sent by the group", () => {
    const hub = new MessageHub();
    const peers = group(hub);
    const [a, b, c] = ["a", "b", "c"].map((name) => child(hub, name)) as [
      ComponentVM, ComponentVM, ComponentVM,
    ];
    const log = interleaved(hub, peers);
    const messages = hubMessages(hub);

    peers.add(a);
    peers.insert(0, b);
    peers.move(0, 1);
    peers.move(1, 1);
    peers.setAt(0, c);
    peers.remove(b);
    peers.clear();

    expectHubFollowsEachLocalEvent(log, 7);
    expect(messages.every((message) => message.sender === peers)).toBe(true);
  });

  it("publishes nothing after the group is disposed", () => {
    const hub = new MessageHub();
    const peers = group(hub);
    const messages = hubMessages(hub);

    peers.dispose();
    try {
      peers.add(child(hub, "late"));
    } catch {
      // A disposed container may reject the mutation; either way it publishes nothing.
    }

    expect(messages).toEqual([]);
  });
});

describe("GRP-013", () => {
  it("publishes one Reset on outermost batch completion and nothing for an empty batch", () => {
    const hub = new MessageHub();
    const peers = group(hub);
    const log = interleaved(hub, peers);

    peers.batchUpdate().dispose();
    const outer = peers.batchUpdate();
    peers.add(child(hub, "a"));
    const inner = peers.batchUpdate();
    peers.add(child(hub, "b"));
    inner.dispose();
    expect(log).toEqual([]);
    outer.dispose();

    expect(log).toEqual(["local:reset:-1:-1", "hub:reset:-1:-1"]);
  });
});
