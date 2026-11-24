/**
 * Unit tests for HierarchicalVM<TModel, TVM> edge cases.
 *
 * Conformance-level tests live in tests/conformance/hier-001-to-014-hierarchical-vm.test.ts.
 */

import { describe, expect, it } from "vitest";

import {
  HierarchicalVM,
  MessageHub,
  PropertyChangedMessage,
  RxDispatcher,
  TreeStructureChangedMessage,
  ViewModelType,
  find,
  walk,
  walkExpanded,
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

// ---------------------------------------------------------------------------
// Parented ancestors in factory output (ADR-0247 D2)
// ---------------------------------------------------------------------------

describe("ParentedAncestorFactory", () => {
  it("a children factory that returns a parented ancestor is refused and leaves the tree intact", () => {
    const hub = makeHub();
    // leaf's factory returns mid, which is leaf's ancestor once the tree is built.
    let mid!: Node;
    const leafVm = new Node({ hub, name: "leaf", childrenFactory: () => [mid] });
    mid = new Node({ hub, name: "mid", childrenFactory: () => [leafVm] });
    const root = new Node({ hub, name: "root", childrenFactory: () => [mid] });
    expect(root.children).toHaveLength(1);
    expect(mid.children).toHaveLength(1);
    expect(mid.children[0]).toBe(leafVm);

    // mid has a parent, so the factory check walks leaf's ancestors and finds mid
    // (ADR-0247 D2). Without that walk, the already-parented message would fire.
    expect(() => leafVm.children).toThrow(/one of its ancestors/);

    expect(mid.parent).toBe(root);
    expect(leafVm.parent).toBe(mid);
    expect(leafVm.path.map((n) => n.name)).toEqual(["root", "mid", "leaf"]);
  });
});

// ---------------------------------------------------------------------------
// Parented children in factory output keep the already-parented message
// ---------------------------------------------------------------------------

describe("ParentedChildFactory", () => {
  it("a children factory that returns a child of another parent is refused with the pinned message", () => {
    const hub = makeHub();
    const owned = leaf(hub, "owned");
    const owner = parentOf([owned], hub);
    expect(owner.children).toHaveLength(1);
    expect(owned.parent).toBe(owner);

    const thief = new Node({ hub, name: "thief", childrenFactory: () => [owned] });
    expect(() => thief.children).toThrow(
      /^children factory returned an already-parented child$/,
    );

    expect(owned.parent).toBe(owner);
    expect(owner.children[0]).toBe(owned);
  });

  it("a same-tree child that is not an ancestor also gets the pinned message", () => {
    const hub = makeHub();
    const a = leaf(hub, "a");
    const b = new Node({ hub, name: "b", childrenFactory: () => [a] });
    const root = parentOf([a, b], hub);
    expect(root.children).toHaveLength(2);

    expect(() => b.children).toThrow(
      /^children factory returned an already-parented child$/,
    );
    expect(a.parent).toBe(root);
  });
});

// ---------------------------------------------------------------------------
// HIER-018 cycle guard by stored tree root (ADR-0248 R2, cases a to d)
// ---------------------------------------------------------------------------

describe("CycleGuardByStoredRoot", () => {
  it("R2 (a): a node cannot be added under itself", () => {
    const node = leaf(makeHub(), "solo");

    expect(() => node.addChild(node)).toThrow(/HIER-018/);
    expect(node.parent).toBeNull();
  });

  it("R2 (b): a parented candidate from another tree transfers with no cycle error", () => {
    const hub = makeHub();
    const moved = leaf(hub, "moved");
    const oldRoot = parentOf([moved], hub);
    expect(oldRoot.children).toHaveLength(1);
    expect(moved.parent).toBe(oldRoot);
    const newRoot = leaf(hub, "new-root");

    newRoot.addChild(moved);

    expect(moved.parent).toBe(newRoot);
    expect(oldRoot.children).toHaveLength(0);
    expect(moved.path.map((n) => n.name)).toEqual(["new-root", "moved"]);
  });

  it("R2 (c): a parentless candidate that is this tree's root is a cycle", () => {
    const hub = makeHub();
    const child = leaf(hub, "child");
    const root = parentOf([child], hub);
    expect(root.children).toHaveLength(1);

    expect(() => child.addChild(root)).toThrow(/HIER-018/);
    expect(root.parent).toBeNull();
    expect(child.parent).toBe(root);
  });

  it("R2 (d): a parented ancestor in this tree is a cycle, and a parented non-ancestor transfers", () => {
    const hub = makeHub();
    const sibling = leaf(hub, "sibling");
    const deep = leaf(hub, "deep");
    const mid = parentOf([deep], hub);
    const root = parentOf([mid, sibling], hub);
    expect(root.children).toHaveLength(2);
    expect(mid.children).toHaveLength(1);

    // mid is parented and is an ancestor of deep: the walk finds it.
    expect(() => deep.addChild(mid)).toThrow(/HIER-018/);
    expect(mid.parent).toBe(root);
    expect(deep.parent).toBe(mid);

    // sibling is parented in the same tree but is not an ancestor of deep.
    deep.addChild(sibling);
    expect(sibling.parent).toBe(deep);
    expect(root.children).toHaveLength(1);
    expect(root.children[0]).toBe(mid);
    expect(sibling.path).toHaveLength(4);
    expect(sibling.path[0]).toBe(root);
    expect(sibling.path[1]).toBe(mid);
    expect(sibling.path[2]).toBe(deep);
    expect(sibling.path[3]).toBe(sibling);
  });
});

// ---------------------------------------------------------------------------
// Deep chains: walks, depth and path invalidation do not recurse
// ---------------------------------------------------------------------------

const DEEP_CHAIN_LEVELS = 10_000;

/** A chain of `levels` nodes. Children come from factories, so building the
 * chain does not touch the path caches. */
function deepChain(levels: number, hub: IMessageHub, dispatcher: RxDispatcher): Node {
  const build = (depth: number): Node =>
    new Node({
      hub,
      dispatcher,
      name: `n${depth}`,
      childrenFactory: () => (depth + 1 === levels ? [] : [build(depth + 1)]),
    });
  return build(0);
}

// The 10,000-level chains are slow on the CI runners: the walk test takes about
// 5.5 s, over vitest's 5,000 ms default. The 30 s budget covers that CI cost of
// the iterative walk test added for issue #1912. It changes no assertion.
describe("DeepChain", () => {
  it("deep chain: walk, walkExpanded, find and depth reach the last level", () => {
    const root = deepChain(DEEP_CHAIN_LEVELS, makeHub(), RxDispatcher.immediate());

    const nodes = [...walk(root)];
    const last = nodes[nodes.length - 1] as Node;

    expect(nodes).toHaveLength(DEEP_CHAIN_LEVELS);
    expect(last.depth).toBe(DEEP_CHAIN_LEVELS - 1);
    expect(last.path).toHaveLength(DEEP_CHAIN_LEVELS);
    expect([...walkExpanded(root)]).toHaveLength(DEEP_CHAIN_LEVELS);
    expect(find(root, (vm) => vm === last)).toBe(last);
  }, 30_000);

  it("deep chain: a materialized chain moves under a new parent", () => {
    const hub = makeHub();
    const dispatcher = RxDispatcher.immediate();
    const root = deepChain(DEEP_CHAIN_LEVELS, hub, dispatcher);
    // Materialize top-down in a loop, so the move itself is what recurses.
    let last = root;
    while (!last.isLeaf) last = last.children[0] as Node;
    const newRoot = new Node({ hub, dispatcher, name: "new-root" });

    newRoot.addChild(root);

    expect(root.parent).toBe(newRoot);
    expect(last.depth).toBe(DEEP_CHAIN_LEVELS);
    expect(last.path[0]).toBe(newRoot);
    expect(last.path[1]).toBe(root);
    // The move restamps every materialized node with the new root (ADR-0247
    // D1). A batch parked from the deepest node therefore lands on newRoot.
    const orphan = leaf(hub, "orphan");
    last.attachMany([orphan], {
      keyOf: (vm) => vm.name,
      parentKeyOf: () => "missing",
    });
    expect(newRoot.parkedAttachCount).toBe(1);
    expect(last.parkedAttachCount).toBe(1);
  }, 30_000);

  it("deep chain: invalidateSubtree drops every materialized level", () => {
    const root = deepChain(DEEP_CHAIN_LEVELS, makeHub(), RxDispatcher.immediate());
    const nodes = [...walk(root)];
    const first = nodes[1] as Node;
    const last = nodes[nodes.length - 1] as Node;

    root.invalidateSubtree();

    expect(nodes).toHaveLength(DEEP_CHAIN_LEVELS);
    expect(first.parent).toBeNull();
    expect(last.parent).toBeNull();
    expect(last.depth).toBe(0);
    expect(last.path).toHaveLength(1);
    expect(last.path[0]).toBe(last);
  }, 30_000);
});

describe("InvalidateSubtreeOrder", () => {
  it("publishes each children change after its descendants (pre-order tree, post-order changes)", () => {
    const hub = makeHub();
    const dispatcher = RxDispatcher.immediate();
    const shape: Record<string, string[]> = {
      root: ["a", "b"],
      a: ["a1"],
      a1: [],
      b: [],
    };
    const byName = new Map<string, Node>();
    for (const name of ["root", "a", "a1", "b"]) {
      byName.set(
        name,
        new Node({
          hub,
          dispatcher,
          name,
          childrenFactory: () => (shape[name] ?? []).map((child) => byName.get(child) as Node),
        }),
      );
    }
    const root = byName.get("root") as Node;
    expect([...walk(root)].map((vm) => vm.name)).toEqual(["root", "a", "a1", "b"]);

    const published: string[] = [];
    hub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage && message.propertyName === "children") {
        published.push(message.senderName);
      }
    });

    root.invalidateSubtree();

    expect(published).toEqual(["a1", "a", "b", "root"]);
  });
});

describe("WalkOrder", () => {
  it("pins pre-order and child read order on a small tree", () => {
    const hub = makeHub();
    const dispatcher = RxDispatcher.immediate();
    const shape: Record<string, string[]> = {
      root: ["a", "b"],
      a: ["a1", "a2"],
      a1: ["a1x"],
      b: ["b1"],
    };
    const reads: string[] = [];
    const byName = new Map<string, Node>();
    for (const name of ["root", "a", "a1", "a1x", "a2", "b", "b1"]) {
      byName.set(
        name,
        new Node({
          hub,
          dispatcher,
          name,
          childrenFactory: () => {
            reads.push(name);
            return (shape[name] ?? []).map((child) => byName.get(child) as Node);
          },
        }),
      );
    }
    const root = byName.get("root") as Node;
    const expected = ["root", "a", "a1", "a1x", "a2", "b", "b1"];

    expect([...walk(root)].map((vm) => vm.name)).toEqual(expected);
    expect(reads).toEqual(expected);
    expect([...walkExpanded(root)].map((vm) => vm.name)).toEqual(expected);
    expect(find(root, (vm) => vm.name === "b1")).toBe(byName.get("b1"));
    expect(byName.get("a1x")?.depth).toBe(3);
  });
});
