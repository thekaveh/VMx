/**
 * HIER-045 — eager construction skips a disposed child (spec ch. 18 §3, ADR-0258).
 */
import { describe, expect, it } from "vitest";
import {
  ConstructionStatus,
  ConstructionStatusChangedMessage,
  HierarchicalVM,
  MessageHub,
  RxDispatcher,
  ViewModelType,
} from "../../src/index.js";

interface Model {
  key: string;
}

class Node extends HierarchicalVM<Model, Node> {
  constructor(hub: MessageHub, key: string, children: () => Node[], eager = false) {
    super({
      model: { key },
      name: key,
      childrenFactory: children,
      hub,
      dispatcher: RxDispatcher.immediate(),
      eagerChildren: eager,
    });
  }

  override get type(): ViewModelType {
    return ViewModelType.Component;
  }
}

describe("HIER-045", () => {
  it("eager construction skips a disposed child, and the live sibling is constructed", () => {
    const hub = new MessageHub();
    const a = new Node(hub, "a", () => []);
    const b = new Node(hub, "b", () => []);
    const root = new Node(hub, "root", () => [a, b], true);

    const changes: Array<{ sender: string; status: ConstructionStatus }> = [];
    hub.messages.subscribe({
      next: (m: unknown) => {
        if (m instanceof ConstructionStatusChangedMessage) {
          changes.push({ sender: m.senderName, status: m.status });
        }
      },
    });

    root.construct();
    a.dispose();
    root.destruct();
    b.destruct();
    changes.length = 0;

    // Neither call throws; the walk skips the disposed child a.
    expect(() => root.construct()).not.toThrow();
    expect(() => root.reconstruct()).not.toThrow();

    expect(root.status).toBe(ConstructionStatus.Constructed);
    expect(b.status).toBe(ConstructionStatus.Constructed);
    expect(a.status).toBe(ConstructionStatus.Disposed);
    expect(changes.filter((change) => change.sender === "a")).toEqual([]);
  });
});
