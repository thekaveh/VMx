/**
 * Unit tests for TreeSelection<TVM> beyond the HIER-033..HIER-040
 * conformance cases in tests/conformance/hier-033-to-040-tree-selection.test.ts.
 */
import { Observable } from "rxjs";
import { describe, expect, it } from "vitest";

import {
  ComponentVMBase,
  ConstructionStatus,
  HierarchicalVM,
  MessageHub,
  PropertyChangedMessage,
  RxDispatcher,
  TreeSelection,
  ViewModelType,
  type IDispatcher,
  type IMessage,
  type IMessageHub,
} from "../../src/index.js";

class Node extends HierarchicalVM<string, Node> {
  constructor(name: string, hub: IMessageHub, children: () => Node[] = () => []) {
    super({
      model: name,
      name,
      hub,
      dispatcher: RxDispatcher.immediate(),
      childrenFactory: () => children(),
    });
  }

  override get type(): ViewModelType {
    return ViewModelType.Component;
  }
}

/** A hub that counts its live `messages` subscriptions and delivered messages. */
class CountingHub implements IMessageHub {
  readonly inner = new MessageHub();
  active = 0;
  delivered = 0;

  get messages(): Observable<IMessage> {
    return new Observable<IMessage>((subscriber) => {
      this.active += 1;
      const subscription = this.inner.messages.subscribe((message) => {
        this.delivered += 1;
        subscriber.next(message);
      });
      return () => {
        this.active -= 1;
        subscription.unsubscribe();
      };
    });
  }

  send(message: IMessage): void {
    this.inner.send(message);
  }
}

/** root → [A → [AA], B → [BB]], all materialized, on one hub. */
function buildTree(hub: IMessageHub = new MessageHub()): {
  root: Node;
  a: Node;
  aa: Node;
  b: Node;
  bb: Node;
} {
  const aa = new Node("AA", hub);
  const bb = new Node("BB", hub);
  const a = new Node("A", hub, () => [aa]);
  const b = new Node("B", hub, () => [bb]);
  const root = new Node("root", hub, () => [a, b]);
  void root.children;
  void a.children;
  void b.children;
  return { root, a, aa, b, bb };
}

function values(selection: TreeSelection<Node>): Array<Node | null> {
  const seen: Array<Node | null> = [];
  selection.currentChanged.subscribe((value) => seen.push(value));
  return seen;
}

describe("TreeSelection", () => {
  it("selects the root itself", () => {
    const { root } = buildTree();
    const selection = new TreeSelection(root);
    const seen = values(selection);

    selection.select(root);

    expect(selection.current).toBe(root);
    expect(seen).toEqual([root]);
  });

  it("accepts a non-structural root and rejects nodes above it", () => {
    const { root, a, aa, b } = buildTree();
    const selection = new TreeSelection(a);

    expect(selection.canSelect(aa)).toBe(true);
    expect(selection.canSelect(root)).toBe(false);
    expect(selection.canSelect(b)).toBe(false);
  });

  it("watches the new path after a move inside the tree", () => {
    const { root, a, aa, b } = buildTree();
    const selection = new TreeSelection(root);
    selection.select(aa);
    const seen = values(selection);

    b.reparentChild(a);
    expect(selection.current).toBe(aa);

    // B joined the path only after the move; removing it must still clear.
    root.removeChild(b);
    expect(selection.current).toBeNull();
    expect(seen).toEqual([null]);
  });

  it("clears when an ancestor on a different hub leaves the tree", () => {
    const hub1 = new MessageHub();
    const hub2 = new MessageHub();
    const aa = new Node("AA", hub1);
    const a = new Node("A", hub2, () => [aa]);
    const root = new Node("root", hub1, () => [a]);
    void root.children;
    void a.children;
    const selection = new TreeSelection(root);
    selection.select(aa);
    const seen = values(selection);

    a.invalidateChildren();

    expect(selection.current).toBeNull();
    expect(seen).toEqual([null]);
  });

  it("clears when a node on a different hub is removed", () => {
    const hub1 = new MessageHub();
    const hub2 = new MessageHub();
    const aa = new Node("AA", hub1);
    const a = new Node("A", hub2, () => [aa]);
    const root = new Node("root", hub1, () => [a]);
    void root.children;
    void a.children;
    const selection = new TreeSelection(root);
    selection.select(aa);

    root.removeChild(a);

    expect(selection.current).toBeNull();
  });

  it("clears when invalidateSubtree runs on the root", () => {
    const { root, aa } = buildTree();
    const selection = new TreeSelection(root);
    selection.select(aa);
    const seen = values(selection);

    root.invalidateSubtree();

    expect(selection.current).toBeNull();
    expect(seen).toEqual([null]);
  });

  it("clears when the root is disposed", () => {
    const { root, aa } = buildTree();
    const selection = new TreeSelection(root);
    selection.select(aa);
    const seen = values(selection);

    root.dispose();

    expect(selection.current).toBeNull();
    expect(seen).toEqual([null]);
    expect(selection.canSelect(root)).toBe(false);
  });

  it("keeps the selection on messages that leave the path valid", () => {
    const { root, aa, b, bb } = buildTree();
    const selection = new TreeSelection(root);
    selection.select(aa);
    const seen = values(selection);

    b.removeChild(bb);
    root.addChild(new Node("C", root.hub));

    expect(selection.current).toBe(aa);
    expect(seen).toEqual([]);
  });

  it("clears inside a hub transaction when the hub delivers the message", () => {
    const hub = new MessageHub();
    const { root, a, aa } = buildTree(hub);
    const selection = new TreeSelection(root);
    selection.select(aa);
    let insideBatch: Node | null | undefined;

    hub.batch(() => {
      root.removeChild(a);
      insideBatch = selection.current;
    });

    expect(insideBatch).toBe(aa);
    expect(selection.current).toBeNull();
  });

  it("sees consistent state when a subscriber selects re-entrantly", () => {
    const { root, a, aa, b, bb } = buildTree();
    const selection = new TreeSelection(root);
    const seen: Array<Node | null> = [];
    let reselected = false;
    selection.currentChanged.subscribe((value) => {
      seen.push(value);
      expect(selection.current).toBe(value);
      if (value === null && !reselected) {
        reselected = true;
        selection.select(bb);
      }
    });
    selection.select(aa);

    root.removeChild(a);

    expect(seen).toEqual([aa, null, bb]);
    expect(selection.current).toBe(bb);
    // The re-entrant selection watches its own path.
    root.removeChild(b);
    expect(selection.current).toBeNull();
    expect(seen).toEqual([aa, null, bb, null]);
  });

  it("rejects null arguments", () => {
    const { root } = buildTree();

    expect(() => new TreeSelection(null as unknown as Node)).toThrow(TypeError);
    const selection = new TreeSelection(root);
    expect(selection.canSelect(null)).toBe(false);
    expect(selection.canSelect(undefined)).toBe(false);
    expect(() => {
      selection.select(null as unknown as Node);
    }).toThrow(TypeError);
    expect(selection.current).toBeNull();
  });

  it("subscribes once per distinct hub and releases on clear and dispose", () => {
    const hub1 = new CountingHub();
    const hub2 = new CountingHub();
    const aa = new Node("AA", hub1);
    const a = new Node("A", hub2, () => [aa]);
    const root = new Node("root", hub1, () => [a]);
    void root.children;
    void a.children;
    const selection = new TreeSelection(root);

    selection.select(aa);
    expect([hub1.active, hub2.active]).toEqual([1, 1]);
    selection.clear();
    expect([hub1.active, hub2.active]).toEqual([0, 0]);

    selection.select(root);
    expect([hub1.active, hub2.active]).toEqual([1, 0]);
    selection.select(aa);
    expect([hub1.active, hub2.active]).toEqual([1, 1]);

    selection.dispose();
    expect([hub1.active, hub2.active]).toEqual([0, 0]);
    const delivered = hub1.delivered + hub2.delivered;
    root.removeChild(a);
    expect(hub1.delivered + hub2.delivered).toBe(delivered);
  });

  it("never disposes or detaches a node on dispose", () => {
    const { root, a, aa } = buildTree();
    const selection = new TreeSelection(root);
    selection.select(aa);

    selection.dispose();

    expect([root, a, aa].map((node) => node.status)).not.toContain(ConstructionStatus.Disposed);
    expect(aa.parent).toBe(a);
  });
});

// The owning VM forwards currentChanged to its own property notification
// (spec/14 rule 6), as with ExpandableState.
class ExplorerVM extends ComponentVMBase {
  readonly #selection: TreeSelection<Node>;

  constructor(root: Node, hub: IMessageHub, dispatcher: IDispatcher) {
    super({ name: "explorer", hub, dispatcher });
    this.#selection = this.own(new TreeSelection(root));
    this.own(
      this.#selection.currentChanged.subscribe(() => this._notifyPropertyChanged("selectedNode")),
    );
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get selectedNode(): Node | null {
    return this.#selection.current;
  }

  selectNode(node: Node): void {
    this.#selection.select(node);
  }
}

describe("TreeSelection owner forwarding", () => {
  it("publishes selectedNode on the owner's hub for each change", () => {
    const hub = new MessageHub();
    const { root, a, aa } = buildTree(hub);
    const explorer = new ExplorerVM(root, hub, RxDispatcher.immediate());
    explorer.construct();
    const published: string[] = [];
    hub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage && message.sender === explorer) {
        published.push(message.propertyName);
      }
    });

    explorer.selectNode(aa);
    expect(explorer.selectedNode).toBe(aa);
    root.removeChild(a);
    expect(explorer.selectedNode).toBeNull();

    expect(published).toEqual(["selectedNode", "selectedNode"]);
  });

  it("disposes the selection with the owner", () => {
    const { root, aa } = buildTree();
    const explorer = new ExplorerVM(root, new MessageHub(), RxDispatcher.immediate());
    explorer.selectNode(aa);

    explorer.dispose();

    expect(explorer.selectedNode).toBeNull();
    expect(root.status).not.toBe(ConstructionStatus.Disposed);
  });
});
