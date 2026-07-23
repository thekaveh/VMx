import { describe, expect, it } from "vitest";

import {
  HierarchicalVM,
  MessageHub,
  RxDispatcher,
  ViewModelType,
} from "../../src/index.js";

class Node extends HierarchicalVM<string, Node> {
  constructor(
    name: string,
    childrenFactory: (parent: Node) => Iterable<Node> = () => [],
    hub = new MessageHub(),
  ) {
    super({
      model: name,
      name,
      childrenFactory,
      hub,
      dispatcher: RxDispatcher.immediate(),
    });
  }

  override get type(): ViewModelType {
    return ViewModelType.Component;
  }
}

describe("HIER-031", () => {
  it("preflights the complete snapshot before mutation and permits retry", () => {
    const hub = new MessageHub();
    const messages: unknown[] = [];
    hub.messages.subscribe({ next: (message) => messages.push(message) });
    const first = new Node("first", undefined, hub);
    const second = new Node("second", undefined, hub);
    const snapshot = [first, first];
    const root = new Node("root", () => snapshot, hub);

    expect(() => root.children).toThrow(/factory/i);
    expect(first.parent).toBeNull();
    expect(messages).toEqual([]);

    snapshot.splice(0, snapshot.length, first, second);
    expect(root.children).toEqual([first, second]);
    expect(first.parent).toBe(root);
    expect(second.parent).toBe(root);
    expect(messages).toEqual([]);
  });

  it("rejects self, ancestor, and already-parented factory output", () => {
    const nullRoot = new Node(
      "null",
      () => [null as unknown as Node],
    );
    expect(() => nullRoot.children).toThrow(/factory/i);
    expect(nullRoot.parent).toBeNull();

    let selfRoot!: Node;
    selfRoot = new Node("self", () => [selfRoot]);
    expect(() => selfRoot.children).toThrow(/factory/i);
    expect(selfRoot.parent).toBeNull();

    const ancestor = new Node("ancestor");
    const descendant = new Node("descendant", () => [ancestor]);
    ancestor.addChild(descendant);
    expect(() => descendant.children).toThrow(/factory/i);
    expect(descendant.parent).toBe(ancestor);

    const oldParent = new Node("old");
    const attached = new Node("attached");
    oldParent.addChild(attached);
    const newParent = new Node("new", () => [attached]);
    expect(() => newParent.children).toThrow(/factory/i);
    expect(attached.parent).toBe(oldParent);
  });
});
