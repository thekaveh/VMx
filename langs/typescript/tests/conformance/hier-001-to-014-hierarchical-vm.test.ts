// HIER-001..HIER-014 conformance tests — VMx absorption audit Stage 2 (HierarchicalVM).
// See spec/18-hierarchical-vm.md and ADR-0028.

import { describe, expect, it } from "vitest";

import {
  ConstructionStatusChangedMessage,
  declareCapabilities,
  ExpandableState,
  HierarchicalVM,
  MessageHub,
  ModeledCrudCommands,
  PropertyChangedMessage,
  RxDispatcher,
  SearchableState,
  TreeStructureChangedMessage,
  ViewModelType,
  walkExpanded,
} from "../../src/index.js";
import type { HierarchicalVMOptions } from "../../src/index.js";
import type { IMessageHub } from "../../src/services/messageHub.js";
import type { IDispatcher } from "../../src/services/dispatcher.js";
import { ConstructionStatus } from "../../src/lifecycle/status.js";

// ---------------------------------------------------------------------------
// Shared test helpers
// ---------------------------------------------------------------------------

interface MyModel {
  value: string;
}

function makeModel(value = "m"): MyModel {
  return { value };
}

class MyNode extends HierarchicalVM<MyModel, MyNode> {
  constructor(
    opts: Partial<HierarchicalVMOptions<MyModel, MyNode>> & {
      model?: MyModel;
    } = {},
  ) {
    super({
      model: opts.model ?? makeModel(),
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

function makeHub(): IMessageHub {
  return new MessageHub();
}

function makeDispatcher(): IDispatcher {
  return RxDispatcher.immediate();
}

function leafNode(
  hub?: IMessageHub,
  dispatcher?: IDispatcher,
  name?: string,
): MyNode {
  return new MyNode({
    ...(hub !== undefined ? { hub } : {}),
    ...(dispatcher !== undefined ? { dispatcher } : {}),
    ...(name !== undefined ? { name } : {}),
  });
}

function parentNode(
  children: MyNode[],
  hub?: IMessageHub,
  eagerChildren = false,
): MyNode {
  return new MyNode({
    childrenFactory: () => children,
    ...(hub !== undefined ? { hub } : {}),
    eagerChildren,
  });
}

// ---------------------------------------------------------------------------
// HIER-001 — Recursive generic constraint compiles
// ---------------------------------------------------------------------------

describe("HIER-001", () => {
  it("Recursive generic constraint compiles per flavor", () => {
    const node = new MyNode();
    expect(node).not.toBeNull();
    expect(node.isRoot).toBe(true);
    expect(node.depth).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// HIER-002 — Parent is null for root, non-null for non-root
// ---------------------------------------------------------------------------

describe("HIER-002", () => {
  it("Parent is null for root, non-null for non-root", () => {
    const child = leafNode();
    const root = parentNode([child]);

    // Force materialization.
    void root.children;

    expect(root.parent).toBeNull();
    expect(child.parent).toBe(root);
  });
});

// ---------------------------------------------------------------------------
// HIER-003 — Depth derivation
// ---------------------------------------------------------------------------

describe("HIER-003", () => {
  it("Depth derivation — root is 0, child is parent + 1", () => {
    const grandchild = leafNode();
    const child = parentNode([grandchild]);
    const root = parentNode([child]);

    void root.children;
    void child.children;

    expect(root.depth).toBe(0);
    expect(child.depth).toBe(1);
    expect(grandchild.depth).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// HIER-004 — Path materialization and cache identity
// ---------------------------------------------------------------------------

describe("HIER-004", () => {
  it("Path materialization — returns root-first snapshot; cached until reparent", () => {
    const hub = makeHub();
    const grandchild = leafNode(hub);
    const child = parentNode([grandchild], hub);
    const root = parentNode([child], hub);

    void root.children;
    void child.children;

    // 1. Correct path contents.
    const path = grandchild.path;
    expect(path).toEqual([root, child, grandchild]);

    // 2. Same array returned on second call (cached).
    expect(grandchild.path).toBe(path);

    // 3. After reparent, path is recomputed.
    const newRoot = leafNode(hub);
    newRoot.addChild(grandchild);
    expect(grandchild.path).not.toBe(path);
    expect(grandchild.path).toEqual([newRoot, grandchild]);
  });
});

// ---------------------------------------------------------------------------
// HIER-005 — IsLeaf and IsRoot derivation
// ---------------------------------------------------------------------------

describe("HIER-005", () => {
  it("IsLeaf and IsRoot derivation match Parent/Children state", () => {
    const leaf = leafNode();
    const root = parentNode([leaf]);

    void root.children;

    expect(root.isRoot).toBe(true);
    expect(root.isLeaf).toBe(false);
    expect(leaf.isRoot).toBe(false);
    expect(leaf.isLeaf).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// HIER-006 — IsFirst and IsLast position predicates
// ---------------------------------------------------------------------------

describe("HIER-006", () => {
  it("IsFirst and IsLast position predicates", () => {
    const c1 = leafNode();
    const c2 = leafNode();
    const c3 = leafNode();
    const root = parentNode([c1, c2, c3]);

    void root.children;

    expect(c1.isFirst).toBe(true);
    expect(c1.isLast).toBe(false);
    expect(c2.isFirst).toBe(false);
    expect(c2.isLast).toBe(false);
    expect(c3.isFirst).toBe(false);
    expect(c3.isLast).toBe(true);

    // Root has no parent so both false.
    expect(root.isFirst).toBe(false);
    expect(root.isLast).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// HIER-007 — Default lazy child loading
// ---------------------------------------------------------------------------

describe("HIER-007", () => {
  it("Default lazy child loading — children factory not called until first access", () => {
    let factoryInvoked = false;

    const node = new MyNode({
      childrenFactory: () => {
        factoryInvoked = true;
        return [leafNode()];
      },
    });

    expect(factoryInvoked).toBe(false);

    void node.children;
    expect(factoryInvoked).toBe(true);

    factoryInvoked = false;
    void node.children;
    expect(factoryInvoked).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// HIER-008 — Eager child loading via eagerChildren option
// ---------------------------------------------------------------------------

describe("HIER-008", () => {
  it("Eager child loading via eagerChildren constructor option", () => {
    let factoryInvoked = false;
    const leaf = leafNode();

    const root = new MyNode({
      childrenFactory: () => {
        factoryInvoked = true;
        return [leaf];
      },
      eagerChildren: true,
    });

    expect(factoryInvoked).toBe(false);

    root.construct();

    expect(factoryInvoked).toBe(true);
    expect(root.children).toContain(leaf);
  });
});

// ---------------------------------------------------------------------------
// HIER-009 — Depth-first construction order
// ---------------------------------------------------------------------------

describe("HIER-009", () => {
  it("Depth-first construction order — deepest node reaches Constructed first", () => {
    const hub = makeHub();
    const dispatcher = makeDispatcher();
    const order: string[] = [];

    hub.messages.subscribe({
      next: (m: unknown) => {
        if (
          m instanceof ConstructionStatusChangedMessage &&
          m.status === ConstructionStatus.Constructed
        ) {
          order.push(m.senderName);
        }
      },
    });

    const grandchild = new MyNode({
      hub,
      dispatcher,
      name: "grandchild",
      eagerChildren: true,
    });
    const child = new MyNode({
      childrenFactory: () => [grandchild],
      hub,
      dispatcher,
      name: "child",
      eagerChildren: true,
    });
    const root = new MyNode({
      childrenFactory: () => [child],
      hub,
      dispatcher,
      name: "root",
      eagerChildren: true,
    });

    root.construct();

    expect(order).toEqual(["grandchild", "child", "root"]);
  });
});

// ---------------------------------------------------------------------------
// HIER-010 — PropertyChangedMessage on Parent change
// ---------------------------------------------------------------------------

describe("HIER-010", () => {
  it("PropertyChangedMessage on parent change", () => {
    const hub = makeHub();
    const dispatcher = makeDispatcher();

    const propMsgs: PropertyChangedMessage<unknown>[] = [];
    hub.messages.subscribe({
      next: (m: unknown) => {
        if (m instanceof PropertyChangedMessage) propMsgs.push(m);
      },
    });

    const child = new MyNode({ hub, dispatcher });
    const parentVm = new MyNode({ hub, dispatcher });

    parentVm.addChild(child);

    const parentMsg = propMsgs.find(
      (m) => m.propertyName === "parent" && m.sender === child,
    );
    expect(parentMsg).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// HIER-011 — TreeStructureChangedMessage on structural mutations
// ---------------------------------------------------------------------------

describe("HIER-011", () => {
  it("TreeStructureChangedMessage on add / remove / reparent", () => {
    const hub = makeHub();
    const dispatcher = makeDispatcher();

    const treeMsgs: TreeStructureChangedMessage<unknown, unknown>[] = [];
    hub.messages.subscribe({
      next: (m: unknown) => {
        if (m instanceof TreeStructureChangedMessage) treeMsgs.push(m);
      },
    });

    const parentVm = new MyNode({ hub, dispatcher });
    const child = new MyNode({ hub, dispatcher });

    // Add
    parentVm.addChild(child);
    expect(treeMsgs).toHaveLength(1);
    const addMsg = treeMsgs[0]!;
    expect(addMsg.change).toBe("added");
    expect(addMsg.sender).toBe(parentVm);
    expect(addMsg.affected).toBe(child);
    expect(addMsg.index).toBe(0);

    treeMsgs.length = 0;

    // Remove
    parentVm.removeChild(child);
    expect(treeMsgs).toHaveLength(1);
    const remMsg = treeMsgs[0]!;
    expect(remMsg.change).toBe("removed");
    expect(remMsg.index).toBe(0);

    treeMsgs.length = 0;

    // Reparent
    parentVm.addChild(child);
    treeMsgs.length = 0;
    const newParent = new MyNode({ hub, dispatcher });
    newParent.reparentChild(child);
    expect(treeMsgs).toHaveLength(1);
    const repMsg = treeMsgs[0]!;
    expect(repMsg.change).toBe("reparented");
    expect(repMsg.sender).toBe(newParent);
    expect(repMsg.affected).toBe(child);
    expect(repMsg.index).toBe(-1);
  });
});

// ---------------------------------------------------------------------------
// HIER-012 — walkExpanded honors ExpandableState lazy boundary
// ---------------------------------------------------------------------------

// ── HIER-012 helper — defined at module scope so it can use class fields ───

class ExpandableHierNode extends HierarchicalVM<MyModel, ExpandableHierNode> {
  readonly #expansion: ExpandableState;

  constructor(
    children: ExpandableHierNode[],
    initiallyExpanded: boolean,
    hub: IMessageHub,
  ) {
    super({
      model: makeModel(),
      childrenFactory: () => children,
      hub,
    });
    this.#expansion = new ExpandableState(initiallyExpanded);
    // Declare IExpandable capability so walkExpanded's hasCapability check passes.
    declareCapabilities(this, "IExpandable");
  }

  override get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get isExpanded(): boolean {
    return this.#expansion.isExpanded;
  }

  expand(): void {
    this.#expansion.expand();
  }

  canExpand(): boolean {
    return this.#expansion.canExpand();
  }
}

describe("HIER-012", () => {
  it("walkExpanded honors lazy boundaries when ExpandableState gate is composed", () => {
    const hub = makeHub();
    const childLeaf = new ExpandableHierNode([], true, hub);
    const root = new ExpandableHierNode([childLeaf], false, hub);

    void root.children; // force materialization

    const walkedCollapsed = [...walkExpanded(root)];
    // Collapsed root itself is yielded; its children are NOT.
    expect(walkedCollapsed).toHaveLength(1);
    expect(walkedCollapsed[0]).toBe(root);

    root.expand();
    const walkedExpanded2 = [...walkExpanded(root)];
    expect(walkedExpanded2).toHaveLength(2); // root + childLeaf
  });
});

// ---------------------------------------------------------------------------
// HIER-013 — Composition with SearchableState filters materialized portion
// ---------------------------------------------------------------------------

describe("HIER-013", () => {
  it("Composition with SearchableState filters materialized portion", () => {
    const hub = makeHub();
    const dispatcher = makeDispatcher();

    const apple = new MyNode({ model: makeModel("apple"), hub, dispatcher });
    const banana = new MyNode({ model: makeModel("banana"), hub, dispatcher });
    const cherry = new MyNode({ model: makeModel("cherry"), hub, dispatcher });
    const root = parentNode([apple, banana, cherry], hub);

    const search = new SearchableState<MyNode>({
      items: () => root.children as Iterable<MyNode>,
      predicate: (node, term) =>
        node.model.value.toLowerCase().includes(term.toLowerCase()),
      debounceMs: 0,
    });

    let result: MyNode[] = [];
    search.filtered.subscribe({
      next: (items) => {
        result = [...items] as MyNode[];
      },
    });

    search.searchTerm = "an";
    search.search();

    expect(result).toHaveLength(1);
    expect(result[0]!.model.value).toBe("banana");

    search.dispose();
  });
});

// ---------------------------------------------------------------------------
// HIER-014 — Composition with ModeledCrudCommands mutates the tree
// ---------------------------------------------------------------------------

describe("HIER-014", () => {
  it("Composition with ModeledCrudCommands mutates the tree", () => {
    const hub = makeHub();
    const dispatcher = makeDispatcher();

    const root = new MyNode({ hub, dispatcher });
    let current: MyNode | null = null;

    const crud = new ModeledCrudCommands<MyModel, MyNode>({
      current: () => current,
      createNew: () => {
        const child = new MyNode({
          model: makeModel("created"),
          hub,
          dispatcher,
        });
        root.addChild(child);
        current = child;
      },
      updateCurrent: (_vm) => {
        // no-op for this test
      },
      deleteCurrent: (vm) => {
        root.removeChild(vm);
        current = null;
      },
    });

    // Create
    crud.createNewCommand.execute();
    expect(root.children).toHaveLength(1);
    expect(current).not.toBeNull();

    // Delete
    crud.deleteCurrentCommand.execute();
    expect(root.children).toHaveLength(0);
    expect(current).toBeNull();

    crud.dispose();
  });
});
