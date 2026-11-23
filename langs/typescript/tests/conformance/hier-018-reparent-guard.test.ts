// HIER-018 conformance test — reparentChild rejects self- and
// ancestor-reparenting. See spec/18-hierarchical-vm.md §6 and ADR-0037 §2.3.

import { describe, expect, it } from "vitest";
import {
  HierarchicalVM,
  MessageHub,
  TreeStructureChangedMessage,
  ViewModelType,
} from "../../src/index.js";
import type { HierarchicalVMOptions } from "../../src/index.js";
import type { IMessageHub } from "../../src/services/messageHub.js";

interface MyModel {
  value: string;
}

class MyNode extends HierarchicalVM<MyModel, MyNode> {
  constructor(
    opts: Partial<HierarchicalVMOptions<MyModel, MyNode>> = {},
  ) {
    super({
      model: { value: "m" },
      childrenFactory: opts.childrenFactory ?? (() => []),
      ...(opts.hub !== undefined ? { hub: opts.hub } : {}),
      ...(opts.name !== undefined ? { name: opts.name } : {}),
    });
  }

  override get type(): ViewModelType {
    return ViewModelType.Component;
  }
}

describe("HIER-018", () => {
  it("reparentChild rejects self- and ancestor-reparenting and leaves the tree intact", () => {
    const hub: IMessageHub = new MessageHub();
    const leaf = new MyNode({ hub, name: "leaf" });
    const mid = new MyNode({ hub, name: "mid", childrenFactory: () => [leaf] });
    const root = new MyNode({ hub, name: "root", childrenFactory: () => [mid] });
    // Materialize the lazy tree so parent backpointers are wired.
    expect(root.children.map((c) => c.name)).toEqual(["mid"]);
    expect(mid.children.map((c) => c.name)).toEqual(["leaf"]);
    expect(leaf.path.map((n) => n.name)).toEqual(["root", "mid", "leaf"]);

    const structureMessages: TreeStructureChangedMessage<unknown, unknown>[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof TreeStructureChangedMessage) structureMessages.push(m);
    });

    // Self-reparenting raises.
    expect(() => leaf.reparentChild(leaf)).toThrow(/HIER-018/);

    // Reparenting an ancestor under its own descendant raises.
    expect(() => leaf.reparentChild(root)).toThrow(/HIER-018/);
    expect(() => leaf.addChild(leaf)).toThrow(/HIER-018/);
    expect(() => leaf.addChild(root)).toThrow(/HIER-018/);

    // Tree structure unchanged; no message published.
    expect(root.parent).toBeNull();
    expect(mid.parent).toBe(root);
    expect(leaf.parent).toBe(mid);
    expect(leaf.depth).toBe(2);
    expect(structureMessages).toHaveLength(0);

    const newParent = new MyNode({ hub, name: "new-parent" });
    newParent.addChild(leaf);
    expect(mid.children).toEqual([]);
    expect(newParent.children).toEqual([leaf]);
    expect(leaf.parent).toBe(newParent);
    // The addChild transfer publishes exactly one message, and its kind is Reparented.
    expect(structureMessages).toHaveLength(1);
    expect(structureMessages[0]?.change).toBe("reparented");
    expect(structureMessages[0]?.affected).toBe(leaf);
  });

  it("reparentChild and addChild reject a parented ancestor and leave the tree intact", () => {
    const hub: IMessageHub = new MessageHub();
    const leaf = new MyNode({ hub, name: "leaf" });
    const mid = new MyNode({ hub, name: "mid", childrenFactory: () => [leaf] });
    const root = new MyNode({ hub, name: "root", childrenFactory: () => [mid] });
    expect(root.children.map((c) => c.name)).toEqual(["mid"]);
    expect(mid.children.map((c) => c.name)).toEqual(["leaf"]);

    // mid has a parent, so the guard walks leaf's ancestors and finds mid
    // (ADR-0247 D2). The root case above is the parentless O(1) branch.
    expect(() => leaf.reparentChild(mid)).toThrow(/HIER-018/);
    expect(() => leaf.addChild(mid)).toThrow(/HIER-018/);

    expect(root.children).toHaveLength(1);
    expect(root.children[0]).toBe(mid);
    expect(mid.children).toHaveLength(1);
    expect(mid.children[0]).toBe(leaf);
    expect(mid.parent).toBe(root);
    expect(leaf.parent).toBe(mid);
    expect(leaf.path.map((n) => n.name)).toEqual(["root", "mid", "leaf"]);
  });
});
