/**
 * A disposed node refuses structural calls (spec ch. 18 §7.1, ADR-0190).
 */
import { describe, expect, it } from "vitest";
import {
  BatchAttachRejectionReason,
  ConstructionStatus,
  HierarchicalVM,
  MessageHub,
  MissingParentPolicy,
  PropertyChangedMessage,
  RxDispatcher,
  TreeStructureChangedMessage,
  ViewModelType,
} from "../../src/index.js";

interface Model { key: string }

class Node extends HierarchicalVM<Model, Node> {
  constructor(hub: MessageHub, key: string, factory: (parent: Node) => Iterable<Node>) {
    super({
      model: { key },
      name: key,
      childrenFactory: factory,
      hub,
      dispatcher: RxDispatcher.immediate(),
    });
  }

  override get type(): ViewModelType {
    return ViewModelType.Component;
  }
}

const keyOptions = {
  keyOf: (node: Node) => node.model.key,
};

function recorder(hub: MessageHub): unknown[] {
  const messages: unknown[] = [];
  hub.messages.subscribe((message) => {
    if (message instanceof TreeStructureChangedMessage || message instanceof PropertyChangedMessage) {
      messages.push(message);
    }
  });
  return messages;
}

function fixture() {
  const hub = new MessageHub();
  const factoryCalls = { r: 0, aa: 0 };
  const aa = new Node(hub, "aa", () => {
    factoryCalls.aa += 1;
    return [];
  });
  const a = new Node(hub, "a", () => [aa]);
  const b = new Node(hub, "b", () => []);
  const r = new Node(hub, "r", () => {
    factoryCalls.r += 1;
    return factoryCalls.r === 1 ? [a, b] : [];
  });
  const d = new Node(hub, "d", () => []);
  for (const node of [r, a, b, aa, d]) {
    node.construct();
    void node.children;
  }
  return { hub, r, a, b, aa, d, factoryCalls };
}

describe("HIER-041", () => {
  it("refuses every structural call on a disposed node, also the no-op calls", () => {
    const { hub, a, aa, d } = fixture();
    a.dispose();
    expect(a.status).toBe(ConstructionStatus.Disposed);
    const messages = recorder(hub);

    const calls: Array<() => unknown> = [
      () => a.addChild(d),
      () => a.removeChild(aa),
      () => a.reparentChild(d),
      () => a.addChild(aa),
      () => a.removeChild(d),
      () => a.invalidateChildren(),
      () => a.invalidateSubtree(),
      () => a.attachMany([d], { ...keyOptions, parentKeyOf: () => null }),
    ];
    for (const call of calls) expect(call).toThrow(Error);

    expect(a.children).toEqual([aa]);
    expect(aa.parent).toBe(a);
    expect(d.parent).toBeNull();
    expect(messages).toEqual([]);
  });

  it("refuses a transfer out of a disposed parent", () => {
    const { hub, a, b, aa } = fixture();
    a.dispose();
    const messages = recorder(hub);

    expect(() => b.addChild(aa)).toThrow(Error);
    expect(() => b.reparentChild(aa)).toThrow(Error);

    expect(aa.parent).toBe(a);
    expect(a.children).toEqual([aa]);
    expect(b.children).toEqual([]);
    expect(messages).toEqual([]);
  });

  it("rejects a batch candidate under a disposed parent as AttachmentFailed", () => {
    const { hub, r, a, aa, d } = fixture();
    a.dispose();
    const messages = recorder(hub);

    const result = r.attachMany([d], {
      ...keyOptions,
      parentKeyOf: () => "a",
      onMissingParent: MissingParentPolicy.Park,
    });

    expect(result.added).toEqual([]);
    expect(result.orphans).toEqual([]);
    expect(result.rejections.map((rejection) => [rejection.item, rejection.reason])).toEqual([
      [d, BatchAttachRejectionReason.AttachmentFailed],
    ]);
    expect(r.parkedAttachCount).toBe(0);
    expect(d.parent).toBeNull();
    expect(a.children).toEqual([aa]);
    expect(messages).toEqual([]);
  });

  it("skips a disposed descendant in invalidateSubtree and still visits its children", () => {
    const { hub, r, a, aa, factoryCalls } = fixture();
    a.dispose();
    const messages = recorder(hub);

    r.invalidateSubtree();

    expect(r.children).toEqual([]);
    expect(factoryCalls.r).toBe(2);
    void aa.children;
    expect(factoryCalls.aa).toBe(2);
    expect(a.children).toEqual([aa]);
    expect(aa.parent).toBe(a);
    expect(
      messages.filter((message) =>
        message instanceof PropertyChangedMessage &&
        message.sender === a &&
        message.propertyName === "children"),
    ).toEqual([]);
  });

  it("refuses attachMany when the structural root is disposed", () => {
    const hub = new MessageHub();
    const c = new Node(hub, "c", () => []);
    const root = new Node(hub, "root", () => [c]);
    root.construct();
    c.construct();
    void root.children;
    root.dispose();
    const item = new Node(hub, "item", () => []);

    expect(() =>
      c.attachMany([item], {
        ...keyOptions,
        parentKeyOf: () => "missing",
        onMissingParent: MissingParentPolicy.Park,
      }),
    ).toThrow(Error);

    expect(c.status).toBe(ConstructionStatus.Constructed);
    expect(root.parkedAttachCount).toBe(0);
    expect(c.parkedAttachCount).toBe(0);
    expect(item.parent).toBeNull();
  });
});
