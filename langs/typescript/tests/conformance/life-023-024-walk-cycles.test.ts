// LIFE-023, LIFE-024 and LIFE-020: a child-transition walk that closes a cycle
// (spec/02-lifecycle.md §6.1, ADR-0255). A walk that lists its own view-model,
// or that would join a view-model whose walk waits back on it, throws the
// usage error and starts no child, so no view-model stays Constructing. The
// diamond case is the control: two walks that share a child construct all
// three view-models.

import { describe, expect, it } from "vitest";
import {
  ComponentVMBase,
  ConstructionStatus as S,
  GroupVM,
  MessageHub,
  RxDispatcher,
  ViewModelType,
  type IDispatcher,
  type IMessageHub,
} from "../../src/index.js";

/** A leaf VM whose construct and destruct hooks walk `walkList`. */
class WalkerVM extends ComponentVMBase {
  readonly walkList: ComponentVMBase[] = [];
  hookRuns = 0;

  constructor(name: string, hub: IMessageHub, dispatcher: IDispatcher) {
    super({ name, hub, dispatcher });
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  protected override _onConstruct(): void {
    super._onConstruct();
    this.hookRuns += 1;
    this._transitionChildren(this.walkList, true);
  }

  protected override _onDestruct(): void {
    this._transitionChildren(this.walkList, false);
  }
}

function services() {
  return { hub: new MessageHub(), dispatcher: RxDispatcher.immediate() };
}

describe("LIFE-023", () => {
  it("refuses a walk that lists its own view-model and starts no child", () => {
    const { hub, dispatcher } = services();
    const walker = new WalkerVM("walker", hub, dispatcher);
    const sibling = new WalkerVM("sibling", hub, dispatcher);
    walker.walkList.push(walker, sibling);

    expect(() => walker.construct()).toThrow("its own view-model");

    expect(walker.status).toBe(S.Destructed);
    expect(sibling.status).toBe(S.Destructed);
    expect(sibling.hookRuns).toBe(0);
  });
});

describe("LIFE-024", () => {
  it("fails a walk that would join a view-model waiting back on it, and both settle", () => {
    const { hub, dispatcher } = services();
    const p = new WalkerVM("p", hub, dispatcher);
    const q = new WalkerVM("q", hub, dispatcher);
    p.walkList.push(q);
    q.walkList.push(p);

    expect(() => p.construct()).toThrow("walk cycle");

    expect(p.status).toBe(S.Destructed);
    expect(q.status).toBe(S.Destructed);
  });

  it("fails the group when a leaf walk lists its own group, and rolls the group back", () => {
    const { hub, dispatcher } = services();
    const leaf = new WalkerVM("leaf", hub, dispatcher);
    const group = GroupVM.builder<ComponentVMBase>()
      .name("group")
      .services(hub, dispatcher)
      .children(() => [leaf])
      .build();
    leaf.walkList.push(group);

    expect(() => group.construct()).toThrow("walk cycle");

    expect(group.status).toBe(S.Destructed);
    expect(leaf.status).toBe(S.Destructed);
  });
});

describe("LIFE-020", () => {
  it("constructs all three view-models when two walks share a child", () => {
    const { hub, dispatcher } = services();
    const a = new WalkerVM("a", hub, dispatcher);
    const b = new WalkerVM("b", hub, dispatcher);
    const c = new WalkerVM("c", hub, dispatcher);
    a.walkList.push(c);
    b.walkList.push(c);

    a.construct();
    b.construct();

    expect(a.status).toBe(S.Constructed);
    expect(b.status).toBe(S.Constructed);
    expect(c.status).toBe(S.Constructed);
    expect(c.hookRuns).toBe(1);
  });
});
