/**
 * Unit tests for HierarchicalVM<TModel, TVM> edge cases.
 *
 * Conformance-level tests live in tests/conformance/hier-001-to-014-hierarchical-vm.test.ts.
 */

import { describe, expect, it } from "vitest";

import {
  HierarchicalVM,
  MessageHub,
  TreeStructureChangedMessage,
  ViewModelType,
} from "../../src/index.js";
import type { HierarchicalVMOptions } from "../../src/index.js";
import type { IMessageHub } from "../../src/services/messageHub.js";

// ---------------------------------------------------------------------------
// Shared test doubles
// ---------------------------------------------------------------------------

interface Model {
  tag: string;
}

class Node extends HierarchicalVM<Model, Node> {
  constructor(
    opts: Partial<HierarchicalVMOptions<Model, Node>> = {},
  ) {
    super({
      model: opts.model ?? { tag: "" },
      childrenFactory: opts.childrenFactory ?? (() => []),
      ...(opts.hub !== undefined ? { hub: opts.hub } : {}),
      ...(opts.dispatcher !== undefined ? { dispatcher: opts.dispatcher } : {}),
      ...(opts.name !== undefined ? { name: opts.name } : {}),
      ...(opts.hint !== undefined ? { hint: opts.hint } : {}),
      ...(opts.eagerChildren !== undefined ? { eagerChildren: opts.eagerChildren } : {}),
    });
  }

  override get type(): ViewModelType {
    return ViewModelType.Component;
  }
}

function leaf(hub?: IMessageHub, name?: string): Node {
  return new Node({
    ...(hub !== undefined ? { hub } : {}),
    ...(name !== undefined ? { name } : {}),
  });
}

function parentOf(children: Node[], hub?: IMessageHub): Node {
  return new Node({
    childrenFactory: () => children,
    ...(hub !== undefined ? { hub } : {}),
  });
}

function makeHub(): IMessageHub {
  return new MessageHub();
}

// ---------------------------------------------------------------------------
// Empty children factory
// ---------------------------------------------------------------------------

describe("EmptyChildrenFactory", () => {
  it("returns empty array", () => {
    const node = leaf();
    expect(node.children).toEqual([]);
  });

  it("isLeaf is true", () => {
    const node = leaf();
    expect(node.isLeaf).toBe(true);
  });

  it("multiple accesses return same object", () => {
    const node = leaf();
    const first = node.children;
    const second = node.children;
    expect(first).toBe(second);
  });
});

// ---------------------------------------------------------------------------
// Single-node tree
// ---------------------------------------------------------------------------

describe("SingleNodeTree", () => {
  it("path contains only self", () => {
    const node = leaf();
    expect(node.path).toEqual([node]);
  });

  it("depth is zero", () => {
    expect(leaf().depth).toBe(0);
  });

  it("isRoot and isLeaf are true", () => {
    const node = leaf();
    expect(node.isRoot).toBe(true);
    expect(node.isLeaf).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Reparenting
// ---------------------------------------------------------------------------

describe("Reparenting", () => {
  it("reparent updates parent reference", () => {
    const hub = makeHub();
    const child = new Node({ hub });
    const p1 = new Node({ hub });
    const p2 = new Node({ hub });

    p1.addChild(child);
    expect(child.parent).toBe(p1);

    p2.reparentChild(child);
    expect(child.parent).toBe(p2);
    expect(p1.children).not.toContain(child);
    expect(p2.children).toContain(child);
  });

  it("reparent to same parent is a no-op (no message)", () => {
    const hub = makeHub();
    const child = new Node({ hub });
    const p = new Node({ hub });

    p.addChild(child);

    const treeMsgs: TreeStructureChangedMessage<unknown, unknown>[] = [];
    hub.messages.subscribe({
      next: (m: unknown) => {
        if (m instanceof TreeStructureChangedMessage) treeMsgs.push(m);
      },
    });

    p.reparentChild(child); // same parent — no-op
    expect(treeMsgs).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Multiple lazy accesses
// ---------------------------------------------------------------------------

describe("LazyChildrenAccess", () => {
  it("factory invoked exactly once", () => {
    let count = 0;

    const node = new Node({
      childrenFactory: () => {
        count++;
        return [leaf()];
      },
    });

    void node.children;
    void node.children;
    void node.children;
    expect(count).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Path cache invalidation across a chain
// ---------------------------------------------------------------------------

describe("PathCacheInvalidation", () => {
  it("path cache invalidated for whole subtree", () => {
    const hub = makeHub();
    const grandchild = new Node({ hub });
    const child = new Node({ childrenFactory: () => [grandchild], hub });
    const root = new Node({ childrenFactory: () => [child], hub });

    void root.children;
    void child.children;

    const oldChildPath = child.path;
    const oldGcPath = grandchild.path;

    const newRoot = new Node({ hub });
    newRoot.reparentChild(child);

    expect(child.path).not.toBe(oldChildPath);
    expect(grandchild.path).not.toBe(oldGcPath);
    expect(grandchild.path[0]).toBe(newRoot);
  });
});

// ---------------------------------------------------------------------------
// AddChild / RemoveChild messaging
// ---------------------------------------------------------------------------

describe("AddRemoveMessaging", () => {
  it("addChild publishes with correct index", () => {
    const hub = makeHub();
    const parentVm = new Node({ hub });
    const c1 = new Node({ hub });
    const c2 = new Node({ hub });

    const msgs: TreeStructureChangedMessage<unknown, unknown>[] = [];
    hub.messages.subscribe({
      next: (m: unknown) => {
        if (m instanceof TreeStructureChangedMessage) msgs.push(m);
      },
    });

    parentVm.addChild(c1);
    parentVm.addChild(c2);

    expect(msgs[0]!.index).toBe(0);
    expect(msgs[1]!.index).toBe(1);
  });

  it("removeChild is no-op when not in list", () => {
    const hub = makeHub();
    const parentVm = new Node({ hub });
    const orphan = new Node({ hub });

    const msgs: TreeStructureChangedMessage<unknown, unknown>[] = [];
    hub.messages.subscribe({
      next: (m: unknown) => {
        if (m instanceof TreeStructureChangedMessage) msgs.push(m);
      },
    });

    parentVm.removeChild(orphan); // not a child
    expect(msgs).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// IsFirst / IsLast on single child
// ---------------------------------------------------------------------------

describe("SingleChildPredicates", () => {
  it("single child is both first and last", () => {
    const child = leaf();
    const root = parentOf([child]);

    void root.children;

    expect(child.isFirst).toBe(true);
    expect(child.isLast).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Depth across multiple levels
// ---------------------------------------------------------------------------

describe("DepthMultipleLevels", () => {
  it("depth accumulates correctly across 5 levels", () => {
    const nodes: Node[] = [];
    // Build a chain of 5 nodes.
    nodes.push(leaf()); // nodes[4]
    for (let i = 3; i >= 0; i--) {
      const next = nodes[nodes.length - 1]!;
      nodes.push(new Node({ childrenFactory: () => [next] }));
    }
    nodes.reverse(); // nodes[0] = root, nodes[4] = deepest leaf

    // Force materialization top-down.
    for (const n of nodes) {
      void n.children;
    }

    for (let i = 0; i < nodes.length; i++) {
      expect(nodes[i]!.depth).toBe(i);
    }
  });
});

// ---------------------------------------------------------------------------
// Null argument validation
// ---------------------------------------------------------------------------

describe("NullValidation", () => {
  it("addChild throws on null", () => {
    const parentVm = leaf();
    expect(() => parentVm.addChild(null as unknown as Node)).toThrow();
  });

  it("removeChild throws on null", () => {
    const parentVm = leaf();
    expect(() => parentVm.removeChild(null as unknown as Node)).toThrow();
  });

  it("reparentChild throws on null", () => {
    const parentVm = leaf();
    expect(() => parentVm.reparentChild(null as unknown as Node)).toThrow();
  });
});
