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
  constructor(key: string, parentKey: string | null = null) {
    super({ model: { key, parentKey }, childrenFactory: () => [], name: key });
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

describe("HIER-023", () => {
  it("resolves child-before-parent chains to a stable sibling-order fixpoint", () => {
    const root = new Node("root");
    const grandchild = new Node("grandchild", "child-a");
    const childB = new Node("child-b", "parent");
    const childA = new Node("child-a", "parent");
    const parent = new Node("parent");

    const result = attach(root, [grandchild, childB, childA, parent]);

    expect(new Set(result.added)).toEqual(new Set([grandchild, childB, childA, parent]));
    expect(root.children).toEqual([parent]);
    expect(parent.children).toEqual([childB, childA]);
    expect(childA.children).toEqual([grandchild]);
    expect(grandchild.path).toEqual([root, parent, childA, grandchild]);
    expect(result.rejections).toEqual([]);
  });
});

describe("HIER-024", () => {
  it("treats null parent keys as direct children of the structural root", () => {
    const root = new Node("root");
    const first = new Node("first");
    const second = new Node("second");
    const result = attach(root, [first, second]);

    expect(result.added).toEqual([first, second]);
    expect(root.children).toEqual([first, second]);
  });
});

describe("HIER-025", () => {
  it("deduplicates against the tree, the batch, and repeated batches without replacement", () => {
    const root = new Node("root");
    const existing = new Node("existing");
    root.addChild(existing);
    const conflict = new Node("existing");
    const first = new Node("new");
    const batchConflict = new Node("new");

    const result = attach(root, [conflict, first, batchConflict]);

    expect(result.added).toEqual([first]);
    expect(result.duplicates).toEqual([conflict, batchConflict]);
    expect(result.rejections.map((item) => item.reason)).toEqual([
      BatchAttachRejectionReason.DuplicateExistingKey,
      BatchAttachRejectionReason.DuplicateBatchKey,
    ]);
    expect(root.children).toEqual([existing, first]);
    expect(attach(root, [first]).duplicates).toEqual([first]);
    expect(root.children).toEqual([existing, first]);
  });
});

describe("HIER-026", () => {
  it("retries a parked orphan when its parent arrives in a later batch", () => {
    const root = new Node("root");
    const child = new Node("child", "parent");
    expect(attach(root, [child]).orphans).toEqual([child]);
    expect(root.parkedAttachCount).toBe(1);

    const parent = new Node("parent");
    const result = attach(root, [parent]);
    expect(new Set(result.added)).toEqual(new Set([parent, child]));
    expect(child.parent).toBe(parent);
    expect(root.parkedAttachCount).toBe(0);
  });
});

describe("HIER-027", () => {
  it("returns reject-policy orphans without retaining them", () => {
    const root = new Node("root");
    const child = new Node("child", "parent");
    expect(attach(root, [child], MissingParentPolicy.Reject).orphans).toEqual([child]);
    expect(root.parkedAttachCount).toBe(0);
    const parent = new Node("parent");
    attach(root, [parent]);
    expect(child.parent).toBeNull();
    expect(parent.children).toEqual([]);
  });
});

describe("HIER-028", () => {
  it("returns parent-key cycles as terminal non-throwing rejections", () => {
    const root = new Node("root");
    const first = new Node("first", "second");
    const second = new Node("second", "first");
    const result = attach(root, [first, second]);

    expect(result.added).toEqual([]);
    expect(result.orphans).toEqual([]);
    expect(result.rejections.map((item) => item.reason)).toEqual([
      BatchAttachRejectionReason.Cycle,
      BatchAttachRejectionReason.Cycle,
    ]);
    expect(root.parkedAttachCount).toBe(0);
  });
});

describe("HIER-029", () => {
  it("reports typed atomic rejections for attached items and selector failures", () => {
    const root = new Node("root");
    const outside = new Node("outside");
    const attached = new Node("attached");
    outside.addChild(attached);
    const detachedSameKey = new Node("attached");

    const result = attach(root, [attached, detachedSameKey]);
    expect(result.rejections[0]).toMatchObject({
      item: attached,
      reason: BatchAttachRejectionReason.AlreadyAttached,
    });
    expect(attached.parent).toBe(outside);
    expect(outside.children).toEqual([attached]);
    expect(result.added).toEqual([detachedSameKey]);
    expect(root.children).toEqual([detachedSameKey]);

    const failed = root.attachMany([new Node("bad")], {
      keyOf: () => { throw new Error("bad key"); },
      parentKeyOf: () => null,
    });
    expect(failed.rejections[0]?.reason).toBe(BatchAttachRejectionReason.SelectorFailed);
  });
});

describe("HIER-030", () => {
  it("clears root-owned parked items on disposal", () => {
    const root = new Node("root");
    attach(root, [new Node("child", "missing")]);
    expect(root.parkedAttachCount).toBe(1);
    root.dispose();
    expect(root.parkedAttachCount).toBe(0);
  });
});
