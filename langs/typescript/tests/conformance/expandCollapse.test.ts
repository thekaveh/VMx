// Conformance tests: EXP-001..008 — expand / collapse.
// See spec/05-component-vm.md, spec/13-tree-utilities.md, ADR-0015, ADR-0159.

import type { Observable } from "rxjs";
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

// ── EXP-006..008 — expansion commands (ADR-0159) ───────────────────────────

function countChanges(command: { canExecuteChanged: Observable<void> }): {
  count: () => number;
} {
  let count = 0;
  command.canExecuteChanged.subscribe(() => {
    count += 1;
  });
  return { count: () => count };
}

describe("EXP-006", () => {
  it("command predicates track the can* checks and re-fire on each change", () => {
    const state = new ExpandableState();
    const expand = state.expandCommand;
    const collapse = state.collapseCommand;
    const toggle = state.toggleExpansionCommand;
    const changes = [expand, collapse, toggle].map(countChanges);

    expect(expand.canExecute()).toBe(true);
    expect(collapse.canExecute()).toBe(false);
    expect(toggle.canExecute()).toBe(true);

    state.expand();
    expect(changes.map((c) => c.count())).toEqual([1, 1, 1]);
    expect(expand.canExecute()).toBe(false);
    expect(collapse.canExecute()).toBe(true);
    expect(toggle.canExecute()).toBe(true);

    // A no-op verb is not an expansion change.
    state.expand();
    expect(changes.map((c) => c.count())).toEqual([1, 1, 1]);

    state.collapse();
    expect(changes.map((c) => c.count())).toEqual([2, 2, 2]);
    expect(expand.canExecute()).toBe(true);
    expect(collapse.canExecute()).toBe(false);

    expect(state.expandCommand).toBe(expand);
    expect(state.collapseCommand).toBe(collapse);
    expect(state.toggleExpansionCommand).toBe(toggle);
  });
});

describe("EXP-007", () => {
  it("executing each command performs its verb", () => {
    const state = new ExpandableState();
    const observed: boolean[] = [];
    state.isExpandedChanged.subscribe((v) => observed.push(v));

    state.expandCommand.execute();
    expect(state.isExpanded).toBe(true);
    // The predicate is false while expanded, so a second execute is a no-op.
    state.expandCommand.execute();
    expect(observed).toEqual([true]);

    state.collapseCommand.execute();
    expect(state.isExpanded).toBe(false);
    state.collapseCommand.execute();
    expect(observed).toEqual([true, false]);

    state.toggleExpansionCommand.execute();
    expect(state.isExpanded).toBe(true);
    state.toggleExpansionCommand.execute();
    expect(state.isExpanded).toBe(false);
    expect(observed).toEqual([true, false, true, false]);
  });
});

describe("EXP-008", () => {
  it("helper dispose makes its commands inert", () => {
    const state = new ExpandableState();
    const expand = state.expandCommand;
    const collapse = state.collapseCommand;
    const toggle = state.toggleExpansionCommand;
    const observed: boolean[] = [];
    state.isExpandedChanged.subscribe((v) => observed.push(v));

    state.dispose();

    for (const command of [expand, collapse, toggle]) {
      expect(command.canExecute()).toBe(false);
      command.execute();
    }
    expect(state.isExpanded).toBe(false);
    expect(observed).toEqual([]);

    // A command first read after disposal is inert as well.
    const late = new ExpandableState();
    late.dispose();
    for (const command of [
      late.expandCommand,
      late.collapseCommand,
      late.toggleExpansionCommand,
    ]) {
      expect(command.canExecute()).toBe(false);
      command.execute();
    }
    expect(late.isExpanded).toBe(false);
    expect(late.expandCommand).toBe(late.expandCommand);
  });
});

// Dispose path — not a conformance ID, but a regression guard for the
// #disposed idempotence guard and the Subject completion in
// ExpandableState.dispose(). Mirrors the Python tests in
// tests/conformance/test_expand_collapse.py.
describe("ExpandableState.dispose", () => {
  it("is idempotent", () => {
    const state = new ExpandableState(true);
    state.dispose();
    expect(() => state.dispose()).not.toThrow();
  });

  it("completes the isExpandedChanged observable", () => {
    const state = new ExpandableState(false);
    let completed = false;
    state.isExpandedChanged.subscribe({ complete: () => { completed = true; } });
    state.dispose();
    expect(completed).toBe(true);
  });

  it("makes later mutations inert", () => {
    const state = new ExpandableState(false);
    state.dispose();

    state.expand();
    state.collapse();
    state.toggleExpansion();

    expect(state.isExpanded).toBe(false);
  });
});
