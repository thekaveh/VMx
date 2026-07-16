import { describe, expect, it } from "vitest";
import {
  HierarchicalVM,
  MessageHub,
  PropertyChangedMessage,
  RxDispatcher,
  ViewModelType,
} from "../../src/index.js";
import type { HierarchicalVMOptions } from "../../src/index.js";

interface Model { value: string }

class Node extends HierarchicalVM<Model, Node> {
  constructor(opts: Partial<HierarchicalVMOptions<Model, Node>> = {}) {
    super({
      model: opts.model ?? { value: "m" },
      childrenFactory: opts.childrenFactory ?? (() => []),
      hub: opts.hub ?? new MessageHub(),
      dispatcher: opts.dispatcher ?? RxDispatcher.immediate(),
    });
  }

  override get type(): ViewModelType {
    return ViewModelType.Component;
  }
}

describe("HIER-019", () => {
  it("invalidateChildren reloads on next access", () => {
    let calls = 0;
    const root = new Node({
      childrenFactory: () => {
        calls += 1;
        return [new Node()];
      },
    });
    const first = root.children[0];

    root.invalidateChildren();
    const second = root.children[0];

    expect(calls).toBe(2);
    expect(second).not.toBe(first);
  });

  it("invalidateChildren detaches discarded children", () => {
    const root = new Node({ childrenFactory: () => [new Node()] });
    const discarded = root.children[0]!;

    root.invalidateChildren();
    const replacement = root.children[0];

    expect(replacement).not.toBe(discarded);
    expect(discarded.parent).toBeNull();
    expect(discarded.isRoot).toBe(true);
    root.addChild(discarded);
    expect(root.children).toContain(discarded);
  });
});

describe("HIER-020", () => {
  it("invalidateChildren on an unmaterialized node is a no-op", () => {
    let calls = 0;
    const root = new Node({
      childrenFactory: () => {
        calls += 1;
        return [];
      },
    });

    root.invalidateChildren();

    expect(calls).toBe(0);
  });
});

describe("HIER-021", () => {
  it("invalidateSubtree reloads materialized descendants", () => {
    let grandchildCalls = 0;
    const child = new Node({
      childrenFactory: () => {
        grandchildCalls += 1;
        return [new Node()];
      },
    });
    const root = new Node({ childrenFactory: () => [child] });
    void root.children;
    const firstGrandchild = child.children[0];

    root.invalidateSubtree();
    const reloadedChild = root.children[0];
    if (reloadedChild === undefined) throw new Error("expected reloaded child");
    const secondGrandchild = reloadedChild.children[0];

    expect(grandchildCalls).toBe(2);
    expect(secondGrandchild).not.toBe(firstGrandchild);
  });
});

describe("HIER-022", () => {
  it("invalidateChildren publishes children property changed", () => {
    const hub = new MessageHub();
    const seen: Array<PropertyChangedMessage<unknown>> = [];
    hub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage) seen.push(message);
    });
    const root = new Node({ hub, childrenFactory: () => [new Node()] });
    void root.children;

    root.invalidateChildren();

    expect(seen.some((m) => m.sender === root && m.propertyName === "children")).toBe(true);
  });
});
