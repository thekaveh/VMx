import { describe, expect, it } from "vitest";

import {
  ConstructionStatus,
  HierarchicalVM,
  MessageHub,
  RxDispatcher,
  TreeSelection,
  ViewModelType,
} from "../../src/index.js";
import type { IMessage } from "../../src/index.js";

let factoryCalls = 0;

class Node extends HierarchicalVM<string, Node> {
  constructor(
    name: string,
    hub: MessageHub,
    children: () => Node[] = () => [],
  ) {
    super({
      model: name,
      name,
      hub,
      dispatcher: RxDispatcher.immediate(),
      childrenFactory: () => {
        factoryCalls += 1;
        return children();
      },
    });
  }

  override get type(): ViewModelType {
    return ViewModelType.Component;
  }
}

interface Tree {
  hub: MessageHub;
  root: Node;
  a: Node;
  aa: Node;
  b: Node;
}

/** root → [A → [AA], B], all materialized, on one hub. */
function buildTree(): Tree {
  const hub = new MessageHub();
  const aa = new Node("AA", hub);
  const a = new Node("A", hub, () => [aa]);
  const b = new Node("B", hub);
  const root = new Node("root", hub, () => [a, b]);
  void root.children;
  void a.children;
  return { hub, root, a, aa, b };
}

function record(selection: TreeSelection<Node>): {
  values: Array<Node | null>;
  completed: () => boolean;
} {
  const values: Array<Node | null> = [];
  let done = false;
  selection.currentChanged.subscribe({
    next: (value) => values.push(value),
    complete: () => {
      done = true;
    },
  });
  return { values, completed: () => done };
}

describe("HIER-033", () => {
  it("delivers a re-entrant select to every subscriber in order", () => {
    const { root, a, aa } = buildTree();
    const selection = new TreeSelection(root);
    selection.currentChanged.subscribe((value) => {
      if (value === aa) selection.select(a);
    });
    const { values } = record(selection);

    selection.select(aa);

    expect(values).toEqual([aa, a]);
    expect(selection.current).toBe(a);
  });

  it("selects a member and publishes each change once", () => {
    const { root, a, aa } = buildTree();
    const selection = new TreeSelection(root);
    const { values } = record(selection);

    expect(selection.canSelect(root)).toBe(true);
    expect(selection.canSelect(a)).toBe(true);
    expect(selection.canSelect(aa)).toBe(true);

    selection.select(aa);
    expect(selection.current).toBe(aa);
    selection.select(aa);
    expect(values).toEqual([aa]);

    selection.clear();
    expect(selection.current).toBeNull();
    selection.clear();
    expect(values).toEqual([aa, null]);
  });
});

describe("HIER-034", () => {
  it("rejects a node outside the materialized tree", () => {
    const { hub, root, a, b } = buildTree();
    const detached = new Node("detached", hub);
    const otherHub = new MessageHub();
    const otherChild = new Node("other-child", otherHub);
    const otherRoot = new Node("other-root", otherHub, () => [otherChild]);
    void otherRoot.children;
    b.dispose();
    const selection = new TreeSelection(root);
    selection.select(a);
    const { values } = record(selection);
    const callsBefore = factoryCalls;

    for (const node of [detached, otherRoot, otherChild, b]) {
      expect(selection.canSelect(node)).toBe(false);
      expect(() => {
        selection.select(node);
      }).toThrow(Error);
      expect(selection.current).toBe(a);
    }

    expect(values).toEqual([]);
    expect(factoryCalls).toBe(callsBefore);
  });
});

describe("HIER-035", () => {
  it("removing an ancestor of the current node clears the selection", () => {
    const { root, a, aa } = buildTree();
    const selection = new TreeSelection(root);
    selection.select(aa);
    const { values } = record(selection);

    root.removeChild(a);

    expect(selection.current).toBeNull();
    expect(values).toEqual([null]);
  });

  it("removing the current node itself clears the selection", () => {
    const { root, a, aa } = buildTree();
    const selection = new TreeSelection(root);
    selection.select(aa);
    const { values } = record(selection);

    a.removeChild(aa);

    expect(selection.current).toBeNull();
    expect(values).toEqual([null]);
  });
});

describe("HIER-036", () => {
  it("a move inside keeps the selection and a transfer out clears it", () => {
    const { root, a, aa, b } = buildTree();
    const otherHub = new MessageHub();
    const otherRoot = new Node("other-root", otherHub);
    const selection = new TreeSelection(root);
    selection.select(aa);
    const { values } = record(selection);

    b.reparentChild(a);
    expect(selection.current).toBe(aa);
    expect(values).toEqual([]);

    otherRoot.addChild(a);
    expect(a.parent).toBe(otherRoot);
    expect(selection.current).toBeNull();
    expect(values).toEqual([null]);
  });
});

describe("HIER-037", () => {
  it("invalidating an ancestor clears the selection", () => {
    const { root, a, aa } = buildTree();
    const selection = new TreeSelection(root);
    selection.select(aa);
    const { values } = record(selection);

    a.invalidateChildren();

    expect(selection.current).toBeNull();
    expect(values).toEqual([null]);
    expect(aa.status).not.toBe(ConstructionStatus.Disposed);
    expect(aa.parent).toBeNull();
    expect(selection.canSelect(aa)).toBe(false);
  });
});

describe("HIER-038", () => {
  it("disposing an ancestor clears the selection", () => {
    const { root, a, aa } = buildTree();
    const selection = new TreeSelection(root);
    selection.select(aa);
    const { values } = record(selection);

    a.dispose();

    expect(selection.current).toBeNull();
    expect(values).toEqual([null]);
    expect(a.parent).toBe(root);
    expect(aa.parent).toBe(a);
    expect(selection.canSelect(aa)).toBe(false);
  });

  it("disposing the current node clears the selection", () => {
    const { root, aa } = buildTree();
    const selection = new TreeSelection(root);
    selection.select(aa);
    const { values } = record(selection);

    aa.dispose();

    expect(selection.current).toBeNull();
    expect(values).toEqual([null]);
    expect(selection.canSelect(aa)).toBe(false);
  });
});

describe("HIER-039", () => {
  it("select does not navigate", () => {
    const hub = new MessageHub();
    let aFactoryCalls = 0;
    const a = new Node("A", hub, () => {
      aFactoryCalls += 1;
      return [];
    });
    const root = new Node("root", hub, () => [a]);
    void root.children;
    const messages: IMessage[] = [];
    hub.messages.subscribe((message) => messages.push(message));
    const before = [root, a].map((node) => [node.status, node.parent, node.isCurrent]);
    const selection = new TreeSelection(root);

    selection.select(a);

    expect(selection.current).toBe(a);
    expect(aFactoryCalls).toBe(0);
    expect([root, a].map((node) => [node.status, node.parent, node.isCurrent])).toEqual(before);
    expect(messages).toEqual([]);
  });
});

describe("HIER-040", () => {
  it("a disposed selection is inert", () => {
    const { root, a, aa, b } = buildTree();
    const selection = new TreeSelection(root);
    selection.select(aa);
    const { values, completed } = record(selection);

    selection.dispose();

    expect(completed()).toBe(true);
    expect(values).toEqual([]);
    expect(selection.current).toBeNull();
    for (const node of [root, a, aa, b]) {
      expect(selection.canSelect(node)).toBe(false);
    }

    expect(() => {
      selection.select(aa);
      selection.clear();
      b.reparentChild(a);
      a.invalidateChildren();
      root.removeChild(b);
      root.dispose();
      selection.dispose();
    }).not.toThrow();
    expect(selection.current).toBeNull();
    expect(values).toEqual([]);
  });
});
