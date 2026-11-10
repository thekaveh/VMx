// HIER-042..044 — attachMany indexes the materialized subtree of a candidate.
// See spec/18-hierarchical-vm.md §6 and ADR-0212.
import { describe, expect, it } from "vitest";

import {
  BatchAttachRejectionReason,
  HierarchicalVM,
  MissingParentPolicy,
  ViewModelType,
} from "../../src/index.js";

interface Model {
  key: string;
  parentKey: string | null;
}

class Node extends HierarchicalVM<Model, Node> {
  constructor(
    key: string,
    parentKey: string | null = null,
    factory: (self: Node) => Iterable<Node> = () => [],
  ) {
    super({ model: { key, parentKey }, childrenFactory: factory, name: key });
  }

  override get type(): ViewModelType {
    return ViewModelType.Component;
  }
}

function attach(
  root: Node,
  items: Node[],
  onMissingParent: MissingParentPolicy = MissingParentPolicy.Park,
) {
  return root.attachMany(items, {
    keyOf: (node) => node.model.key,
    parentKeyOf: (node) => node.model.parentKey,
    onMissingParent,
  });
}

describe("HIER-042", () => {
  it("attaches a candidate below a node of an attached subtree", () => {
    const root = new Node("root");
    const p = new Node("p");
    const c = new Node("c");
    p.addChild(c);
    const x = new Node("x", "c");

    const result = attach(root, [p, x]);

    expect(result.added).toEqual([p, x]);
    expect(result.rejections).toEqual([]);
    expect(result.orphans).toEqual([]);
    expect(result.duplicates).toEqual([]);
    expect(root.children).toEqual([p]);
    expect(p.children).toEqual([c]);
    expect(c.children).toEqual([x]);
    expect(x.path).toEqual([root, p, c, x]);
    expect(root.parkedAttachCount).toBe(0);
  });

  it("rejects a parent key that names the candidate's own descendant as a cycle", () => {
    let calls = 0;
    const root = new Node("root");
    const q = new Node("q", "d");
    const d = new Node("d", null, () => {
      calls += 1;
      return [];
    });
    q.addChild(d);

    const result = attach(root, [q], MissingParentPolicy.Park);

    // Checked first: a deep equality on a node iterates its children.
    expect(calls).toBe(0);
    expect(result.added).toHaveLength(0);
    expect(result.orphans).toHaveLength(0);
    expect(result.rejections).toHaveLength(1);
    expect(result.rejections[0]?.item).toBe(q);
    expect(result.rejections[0]?.reason).toBe(BatchAttachRejectionReason.Cycle);
    expect(root.parkedAttachCount).toBe(0);
    expect(q.parent).toBeNull();
  });
});

describe("HIER-043", () => {
  it("rejects a candidate whose descendant key is in the index", () => {
    const root = new Node("root");
    const existing = new Node("c");
    root.addChild(existing);
    const p = new Node("p");
    const inner = new Node("c");
    p.addChild(inner);

    const result = attach(root, [p]);

    expect(result.added).toEqual([]);
    expect(result.duplicates).toEqual([p]);
    expect(result.rejections).toEqual([
      { item: p, reason: BatchAttachRejectionReason.DuplicateExistingKey },
    ]);
    expect(p.parent).toBeNull();
    expect(p.children).toEqual([inner]);
    expect(root.children).toEqual([existing]);
  });

  it("rejects a later candidate whose key a subtree claimed first", () => {
    const root = new Node("root");
    const p = new Node("p");
    const c = new Node("c");
    p.addChild(c);
    const c2 = new Node("c", "p");

    const result = attach(root, [p, c2]);

    expect(result.added).toEqual([p]);
    expect(result.duplicates).toEqual([c2]);
    expect(result.rejections).toEqual([
      { item: c2, reason: BatchAttachRejectionReason.DuplicateBatchKey },
    ]);
    expect(p.children).toEqual([c]);
    expect(c2.parent).toBeNull();
  });

  it("rejects a subtree that repeats an earlier candidate key", () => {
    const root = new Node("root");
    const p = new Node("p");
    const c = new Node("c");
    p.addChild(c);
    const c2 = new Node("c", "p");

    const result = attach(root, [c2, p]);

    expect(result.added).toEqual([]);
    expect(result.duplicates).toEqual([p]);
    expect(result.rejections).toContainEqual({
      item: p,
      reason: BatchAttachRejectionReason.DuplicateBatchKey,
    });
    expect(result.orphans).toEqual([c2]);
    expect(result.rejections).toContainEqual({
      item: c2,
      reason: BatchAttachRejectionReason.MissingParent,
    });
    expect(p.parent).toBeNull();
    expect(c2.parent).toBeNull();
    expect(p.children).toEqual([c]);
  });
});

describe("HIER-043", () => {
  it.each([false, true])(
    "rejects a node of an earlier subtree as AlreadyAttached (child first: %s)",
    (childFirst) => {
      const root = new Node("root");
      const p = new Node("p");
      const c = new Node("c");
      p.addChild(c);

      const result = attach(root, childFirst ? [c, p] : [p, c]);

      expect(result.added).toHaveLength(1);
      expect(result.added[0]).toBe(p);
      expect(result.duplicates).toHaveLength(0);
      expect(result.rejections).toHaveLength(1);
      expect(result.rejections[0]?.item).toBe(c);
      expect(result.rejections[0]?.reason).toBe(BatchAttachRejectionReason.AlreadyAttached);
      expect(c.parent).toBe(p);
      expect(p.children).toHaveLength(1);
      expect(p.children[0]).toBe(c);
    },
  );

  it("rejects a candidate whose own subtree repeats a key", () => {
    const root = new Node("root");
    const p = new Node("p");
    const d1 = new Node("d");
    const d2 = new Node("d");
    p.addChild(d1);
    p.addChild(d2);

    const result = attach(root, [p]);

    expect(result.added).toHaveLength(0);
    expect(result.duplicates).toHaveLength(1);
    expect(result.duplicates[0]).toBe(p);
    expect(result.rejections).toHaveLength(1);
    expect(result.rejections[0]?.item).toBe(p);
    expect(result.rejections[0]?.reason).toBe(BatchAttachRejectionReason.DuplicateBatchKey);
    expect(p.parent).toBeNull();
    expect(p.children).toHaveLength(2);
    expect(p.children[0]).toBe(d1);
    expect(p.children[1]).toBe(d2);
  });

  it("keeps a parked candidate parked when a descendant keyOf fails", () => {
    const attachFailing = (root: Node, items: Node[]) =>
      root.attachMany(items, {
        keyOf: (node) => {
          if (node.model.key === "bad") throw new Error("keyOf failed");
          return node.model.key;
        },
        parentKeyOf: (node) => node.model.parentKey,
        onMissingParent: MissingParentPolicy.Park,
      });
    const root = new Node("root");
    const p = new Node("p", "m");
    const parked = attachFailing(root, [p]);
    expect(parked.orphans).toHaveLength(1);
    expect(parked.orphans[0]).toBe(p);
    expect(root.parkedAttachCount).toBe(1);
    p.addChild(new Node("bad"));

    const result = attachFailing(root, []);

    expect(result.added).toHaveLength(0);
    expect(result.duplicates).toHaveLength(0);
    expect(result.rejections).toHaveLength(1);
    expect(result.rejections[0]?.item).toBe(p);
    expect(result.rejections[0]?.reason).toBe(BatchAttachRejectionReason.SelectorFailed);
    expect(root.parkedAttachCount).toBe(1);
    expect(p.parent).toBeNull();
  });
});

describe("HIER-044", () => {
  it("indexes children that addChild materializes only in the next batch", () => {
    const root = new Node("root");
    const f = new Node("f");
    const lazy = new Node("L", null, () => [f]);
    root.addChild(lazy);
    const y = new Node("y", "L");
    const z = new Node("z", "f");

    const first = attach(root, [y, z], MissingParentPolicy.Park);

    expect(first.added).toEqual([y]);
    expect(lazy.children).toEqual([f, y]);
    expect(first.orphans).toEqual([z]);
    expect(first.rejections).toEqual([
      { item: z, reason: BatchAttachRejectionReason.MissingParent },
    ]);
    expect(root.parkedAttachCount).toBe(1);

    const second = attach(root, []);

    expect(second.added).toEqual([z]);
    expect(second.rejections).toEqual([]);
    expect(z.parent).toBe(f);
    expect(root.parkedAttachCount).toBe(0);
  });
});
