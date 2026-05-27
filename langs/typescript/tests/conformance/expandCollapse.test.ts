// Conformance tests: EXP-001..005 — expand / collapse.
// See spec/05-component-vm.md, spec/13-tree-utilities.md, ADR-0015.

import { describe, expect, it } from "vitest";

import {
  declareCapabilities,
  ExpandableState,
  walkExpanded,
} from "../../src/index.js";
import { ComponentVMBase } from "../../src/components/componentVMBase.js";
import { ViewModelType } from "../../src/components/types.js";

describe("EXP-001", () => {
  it("ExpandableState defaults to collapsed", () => {
    const e = new ExpandableState();
    expect(e.isExpanded).toBe(false);
    expect(e.canExpand()).toBe(true);
    expect(e.canCollapse()).toBe(false);
  });
});

describe("EXP-002", () => {
  it("Expand flips state and emits IsExpandedChanged once", () => {
    const e = new ExpandableState();
    const observed: boolean[] = [];
    e.isExpandedChanged.subscribe((v) => observed.push(v));
    e.expand();
    expect(e.isExpanded).toBe(true);
    expect(observed).toEqual([true]);
    e.expand();
    expect(observed).toEqual([true]);
  });
});

describe("EXP-003", () => {
  it("Collapse flips state back, emits change", () => {
    const e = new ExpandableState(true);
    const observed: boolean[] = [];
    e.isExpandedChanged.subscribe((v) => observed.push(v));
    e.collapse();
    expect(e.isExpanded).toBe(false);
    expect(observed).toEqual([false]);
  });
});

describe("EXP-004", () => {
  it("ToggleExpansion alternates state", () => {
    const e = new ExpandableState();
    e.toggleExpansion();
    e.toggleExpansion();
    expect(e.isExpanded).toBe(false);
    e.toggleExpansion();
    expect(e.isExpanded).toBe(true);
  });
});

// ── EXP-005 — fixture-style test ───────────────────────────────────────────

class FakeLeaf extends ComponentVMBase {
  override get type(): ViewModelType {
    return ViewModelType.Component;
  }
}

function makeLeaf(name: string): FakeLeaf {
  // Minimal init that satisfies the base ctor (uses a null-style hub/dispatcher).
  return new FakeLeaf({
    name,
    hint: "",
    hub: {
      messages: { subscribe: () => ({ unsubscribe: () => undefined }) },
      send: () => undefined,
    } as never,
    dispatcher: {
      foreground: { schedule: () => undefined },
      background: { schedule: () => undefined },
    } as never,
  });
}

class ExpandableComposite extends ComponentVMBase {
  readonly #children: ComponentVMBase[];
  isExpanded: boolean;

  constructor(name: string, children: ComponentVMBase[], expanded: boolean) {
    super({
      name,
      hint: "",
      hub: {
      messages: { subscribe: () => ({ unsubscribe: () => undefined }) },
      send: () => undefined,
    } as never,
      dispatcher: {
      foreground: { schedule: () => undefined },
      background: { schedule: () => undefined },
    } as never,
    });
    this.#children = children;
    this.isExpanded = expanded;
    declareCapabilities(this, "IExpandable");
  }

  override get type(): ViewModelType {
    return ViewModelType.Component;
  }

  *[Symbol.iterator](): IterableIterator<ComponentVMBase> {
    yield* this.#children;
  }

  canExpand(): boolean {
    return !this.isExpanded;
  }

  expand(): void {
    this.isExpanded = true;
  }
}

describe("EXP-005", () => {
  it("walkExpanded skips descendants of collapsed nodes", () => {
    const a = makeLeaf("a");
    const b1 = makeLeaf("b1");
    const b2 = makeLeaf("b2");
    const bCollapsed = new ExpandableComposite("b", [b1, b2], false);
    const root = new ExpandableComposite("root", [a, bCollapsed], true);

    const visited = [...walkExpanded(root)];
    expect(visited).toContain(root);
    expect(visited).toContain(a);
    expect(visited).toContain(bCollapsed);
    expect(visited).not.toContain(b1);
    expect(visited).not.toContain(b2);
  });
});
