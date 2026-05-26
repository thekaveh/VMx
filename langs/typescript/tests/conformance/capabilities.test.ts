// Conformance tests: CAP-001..020 — capability micro-interfaces.
// See spec/14-capabilities.md and ADR-0010.

import { describe, expect, it } from "vitest";

import {
  ComponentVMBuilder,
  declareCapabilities,
  hasCapability,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";
import type {
  IApprovable,
  ICancelable,
  IClosable,
  ICollapsible,
  IConstructable,
  ICurrentDeletable,
  ICurrentUpdatable,
  IDeletable,
  IDeselectable,
  IDestructable,
  IExpandable,
  IExpansionTogglable,
  IManagable,
  INewCreatable,
  IReconstructable,
  ISavable,
  ISearchable,
  ISelectable,
  ISelectionTogglable,
  IUpdatable,
} from "../../src/index.js";

function bareComponentVM() {
  return new ComponentVMBuilder()
    .name("bare")
    .services(new MessageHub(), RxDispatcher.immediate())
    .build();
}

describe("CAP-001", () => {
  it("ISelectable contract", () => {
    class F implements ISelectable {
      calls = 0;
      constructor() {
        declareCapabilities(this, "ISelectable");
      }
      canSelect() {
        return true;
      }
      select() {
        this.calls++;
      }
    }
    const f = new F();
    expect(f.canSelect()).toBe(true);
    f.select();
    expect(f.calls).toBe(1);
  });
});

describe("CAP-002", () => {
  it("IDeselectable contract", () => {
    class F implements IDeselectable {
      calls = 0;
      constructor() {
        declareCapabilities(this, "IDeselectable");
      }
      canDeselect() {
        return true;
      }
      deselect() {
        this.calls++;
      }
    }
    const f = new F();
    expect(f.canDeselect()).toBe(true);
    f.deselect();
    expect(f.calls).toBe(1);
  });
});

describe("CAP-003", () => {
  it("ISelectionTogglable contract", () => {
    class F implements ISelectionTogglable {
      selected = false;
      constructor() {
        declareCapabilities(this, "ISelectionTogglable");
      }
      canToggleSelection() {
        return true;
      }
      toggleSelection() {
        this.selected = !this.selected;
      }
    }
    const f = new F();
    const initial = f.selected;
    expect(f.canToggleSelection()).toBe(true);
    f.toggleSelection();
    f.toggleSelection();
    expect(f.selected).toBe(initial);
  });
});

describe("CAP-004", () => {
  it("IExpandable contract", () => {
    class F implements IExpandable {
      isExpanded = false;
      constructor() {
        declareCapabilities(this, "IExpandable");
      }
      canExpand() {
        return true;
      }
      expand() {
        this.isExpanded = true;
      }
    }
    const f = new F();
    expect(f.isExpanded).toBe(false);
    expect(f.canExpand()).toBe(true);
    f.expand();
    expect(f.isExpanded).toBe(true);
  });
});

describe("CAP-005", () => {
  it("ICollapsible contract", () => {
    class F implements ICollapsible {
      calls = 0;
      constructor() {
        declareCapabilities(this, "ICollapsible");
      }
      canCollapse() {
        return true;
      }
      collapse() {
        this.calls++;
      }
    }
    const f = new F();
    expect(f.canCollapse()).toBe(true);
    f.collapse();
    expect(f.calls).toBe(1);
  });
});

describe("CAP-006", () => {
  it("IExpansionTogglable contract", () => {
    class F implements IExpansionTogglable {
      expanded = false;
      constructor() {
        declareCapabilities(this, "IExpansionTogglable");
      }
      canToggleExpansion() {
        return true;
      }
      toggleExpansion() {
        this.expanded = !this.expanded;
      }
    }
    const f = new F();
    const initial = f.expanded;
    expect(f.canToggleExpansion()).toBe(true);
    f.toggleExpansion();
    f.toggleExpansion();
    expect(f.expanded).toBe(initial);
  });
});

describe("CAP-007", () => {
  it("IClosable contract", () => {
    class F implements IClosable {
      calls = 0;
      constructor() {
        declareCapabilities(this, "IClosable");
      }
      canClose() {
        return true;
      }
      close() {
        this.calls++;
      }
    }
    const f = new F();
    expect(f.canClose()).toBe(true);
    f.close();
    expect(f.calls).toBe(1);
  });
});

describe("CAP-008", () => {
  it("ISearchable contract", () => {
    class F implements ISearchable {
      searchTerm = "";
      searched: string[] = [];
      constructor() {
        declareCapabilities(this, "ISearchable");
      }
      canSearch() {
        return true;
      }
      search() {
        this.searched.push(this.searchTerm);
      }
    }
    const f = new F();
    f.searchTerm = "abc";
    expect(f.canSearch()).toBe(true);
    f.search();
    expect(f.searchTerm).toBe("abc");
    expect(f.searched).toEqual(["abc"]);
  });
});

describe("CAP-009", () => {
  it("IApprovable contract", () => {
    class F implements IApprovable {
      calls = 0;
      constructor() {
        declareCapabilities(this, "IApprovable");
      }
      canApprove() {
        return true;
      }
      approve() {
        this.calls++;
      }
    }
    const f = new F();
    expect(f.canApprove()).toBe(true);
    f.approve();
    expect(f.calls).toBe(1);
  });
});

describe("CAP-010", () => {
  it("ICancelable contract", () => {
    class F implements ICancelable {
      calls = 0;
      constructor() {
        declareCapabilities(this, "ICancelable");
      }
      canCancel() {
        return true;
      }
      cancel() {
        this.calls++;
      }
    }
    const f = new F();
    expect(f.canCancel()).toBe(true);
    f.cancel();
    expect(f.calls).toBe(1);
  });
});

describe("CAP-011", () => {
  it("ISavable<T> contract", () => {
    class F implements ISavable<string> {
      saved: string[] = [];
      constructor() {
        declareCapabilities(this, "ISavable");
      }
      canSave(_item: string) {
        return true;
      }
      save(item: string) {
        this.saved.push(item);
      }
    }
    const f = new F();
    expect(f.canSave("a")).toBe(true);
    f.save("a");
    expect(f.saved).toEqual(["a"]);
  });
});

describe("CAP-012", () => {
  it("IManagable<T> contract", () => {
    class F implements IManagable<string> {
      managed: string[] = [];
      constructor() {
        declareCapabilities(this, "IManagable");
      }
      canManage(_item: string) {
        return true;
      }
      manage(item: string) {
        this.managed.push(item);
      }
    }
    const f = new F();
    expect(f.canManage("x")).toBe(true);
    f.manage("x");
    expect(f.managed).toEqual(["x"]);
  });
});

describe("CAP-013", () => {
  it("INewCreatable contract", () => {
    class F implements INewCreatable {
      calls = 0;
      constructor() {
        declareCapabilities(this, "INewCreatable");
      }
      canCreateNew() {
        return true;
      }
      createNew() {
        this.calls++;
      }
    }
    const f = new F();
    expect(f.canCreateNew()).toBe(true);
    f.createNew();
    expect(f.calls).toBe(1);
  });
});

describe("CAP-014", () => {
  it("IDeletable<T> contract", () => {
    class F implements IDeletable<string> {
      deleted: string[] = [];
      constructor() {
        declareCapabilities(this, "IDeletable");
      }
      canDelete(_item: string) {
        return true;
      }
      delete(item: string) {
        this.deleted.push(item);
      }
    }
    const f = new F();
    expect(f.canDelete("a")).toBe(true);
    f.delete("a");
    expect(f.deleted).toEqual(["a"]);
  });
});

describe("CAP-015", () => {
  it("IUpdatable<T> contract", () => {
    class F implements IUpdatable<string> {
      updated: string[] = [];
      constructor() {
        declareCapabilities(this, "IUpdatable");
      }
      canUpdate(_item: string) {
        return true;
      }
      update(item: string) {
        this.updated.push(item);
      }
    }
    const f = new F();
    expect(f.canUpdate("a")).toBe(true);
    f.update("a");
    expect(f.updated).toEqual(["a"]);
  });
});

describe("CAP-016", () => {
  it("ICurrentDeletable contract", () => {
    class F implements ICurrentDeletable {
      calls = 0;
      constructor() {
        declareCapabilities(this, "ICurrentDeletable");
      }
      canDeleteCurrent() {
        return true;
      }
      deleteCurrent() {
        this.calls++;
      }
    }
    const f = new F();
    expect(f.canDeleteCurrent()).toBe(true);
    f.deleteCurrent();
    expect(f.calls).toBe(1);
  });
});

describe("CAP-017", () => {
  it("ICurrentUpdatable contract", () => {
    class F implements ICurrentUpdatable {
      calls = 0;
      constructor() {
        declareCapabilities(this, "ICurrentUpdatable");
      }
      canUpdateCurrent() {
        return true;
      }
      updateCurrent() {
        this.calls++;
      }
    }
    const f = new F();
    expect(f.canUpdateCurrent()).toBe(true);
    f.updateCurrent();
    expect(f.calls).toBe(1);
  });
});

describe("CAP-018", () => {
  it("Lifecycle capability set", () => {
    class F implements IConstructable, IDestructable, IReconstructable {
      constructor() {
        declareCapabilities(
          this,
          "IConstructable",
          "IDestructable",
          "IReconstructable",
        );
      }
      canConstruct() {
        return true;
      }
      construct() {}
      canDestruct() {
        return true;
      }
      destruct() {}
      canReconstruct() {
        return true;
      }
      reconstruct() {}
    }
    const f = new F();
    for (const op of [
      "canConstruct",
      "construct",
      "canDestruct",
      "destruct",
      "canReconstruct",
      "reconstruct",
    ] as const) {
      expect(typeof (f as unknown as Record<string, unknown>)[op]).toBe(
        "function",
      );
    }
  });
});

describe("CAP-019", () => {
  it("A single VM may implement multiple capabilities", () => {
    class F
      implements ISelectable, IExpandable, IClosable, IApprovable, ICancelable
    {
      selects = 0;
      expands = 0;
      closes = 0;
      approves = 0;
      cancels = 0;
      isExpanded = false;
      constructor() {
        declareCapabilities(
          this,
          "ISelectable",
          "IExpandable",
          "IClosable",
          "IApprovable",
          "ICancelable",
        );
      }
      canSelect() {
        return true;
      }
      select() {
        this.selects++;
      }
      canExpand() {
        return true;
      }
      expand() {
        this.isExpanded = true;
        this.expands++;
      }
      canClose() {
        return true;
      }
      close() {
        this.closes++;
      }
      canApprove() {
        return true;
      }
      approve() {
        this.approves++;
      }
      canCancel() {
        return true;
      }
      cancel() {
        this.cancels++;
      }
    }
    const f = new F();
    for (const cap of [
      "ISelectable",
      "IExpandable",
      "IClosable",
      "IApprovable",
      "ICancelable",
    ] as const) {
      expect(hasCapability(f, cap)).toBe(true);
    }
    f.select();
    f.expand();
    f.close();
    f.approve();
    f.cancel();
    expect([f.selects, f.expands, f.closes, f.approves, f.cancels]).toEqual([
      1, 1, 1, 1, 1,
    ]);
  });
});

describe("CAP-020", () => {
  it("Core ComponentVM does NOT implement non-baseline capabilities by default", () => {
    const vm = bareComponentVM();
    for (const cap of [
      "ISelectable",
      "IExpandable",
      "IClosable",
      "INewCreatable",
      "ICurrentDeletable",
      "ISearchable",
    ] as const) {
      expect(hasCapability(vm, cap)).toBe(false);
    }
    for (const cap of [
      "IConstructable",
      "IDestructable",
      "IReconstructable",
    ] as const) {
      expect(hasCapability(vm, cap)).toBe(true);
    }
  });
});
