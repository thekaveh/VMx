/**
 * Attack round 2: memoization with fresh objects and the development staleness check.
 *
 * Expectations used: R19.1 "The check evaluates the getter untracked in a probe frame and compares by
 * the node's equality, then by deep structural equality ... so a fresh `new Range(...)` or `new Map(...)` built from
 * tracked state is not reported"; RSTATE-010 glitch freedom.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM, PropertyChangedMessage } from "@thekaveh/vmx";
import { activate, configureReactiveDiagnostics, shallowEqual } from "../src/index.js";
import { base, captureReports, type Services, services, tick } from "./support.js";

function hubNames(s: Services, sender: object): string[] {
  const names: string[] = [];
  s.hub.messages.subscribe((m) => {
    if (m instanceof PropertyChangedMessage && m.sender === sender) names.push(m.propertyName);
  });
  return names;
}

describe("attack-r2 memoization with fresh objects", () => {
  it("MM1 the staleness check does not report a computed whose fresh object carries a fresh callback", async () => {
    configureReactiveDiagnostics({ development: true });
    try {
      const reports = captureReports();
      const s = services();
      class Menu extends ComponentVM {
        declare label: string;
        constructor() {
          super(base(s, "menu"));
          this.observable({ label: "Share" });
          this.computed("item");
        }
        /** A menu entry built from tracked state: the run callback is a fresh closure on every evaluation. */
        get item(): { readonly label: string; readonly run: () => void } {
          return { label: this.label, run: () => undefined };
        }
      }
      const vm = new Menu();
      activate(vm);
      void vm.item; // a consumer read schedules the check
      await tick();
      await tick();
      assert.deepEqual(reports, []);
    } finally {
      configureReactiveDiagnostics({ development: undefined });
    }
  });

  it("MM2 the staleness check does not report a fresh object graph with a back reference", async () => {
    configureReactiveDiagnostics({ development: true });
    try {
      const reports = captureReports();
      const s = services();
      interface TreeNode {
        readonly label: string;
        parent: TreeNode | null;
        readonly children: TreeNode[];
      }
      class Tree extends ComponentVM {
        declare rootLabel: string;
        constructor() {
          super(base(s, "tree"));
          this.observable({ rootLabel: "root" });
          this.computed("root");
        }
        get root(): TreeNode {
          const root: TreeNode = { label: this.rootLabel, parent: null, children: [] };
          root.children.push({ label: "child", parent: root, children: [] });
          return root;
        }
      }
      const vm = new Tree();
      activate(vm);
      void vm.root;
      await tick();
      await tick();
      assert.deepEqual(reports, []);
    } finally {
      configureReactiveDiagnostics({ development: undefined });
    }
  });

  it("MM3 a diamond whose fresh-array branch is stabilized by shallowEqual evaluates and announces the join once (expected to hold)", () => {
    const s = services();
    class Diamond extends ComponentVM {
      declare n: number;
      evaluations = 0;
      constructor() {
        super(base(s, "diamond"));
        this.observable({ n: 1 });
        this.computed({ parity: shallowEqual, size: Object.is, joined: Object.is });
      }
      get parity(): readonly string[] {
        return [this.n % 2 === 0 ? "even" : "odd"];
      }
      get size(): number {
        return this.n;
      }
      get joined(): string {
        this.evaluations += 1;
        return `${this.parity.join("")}:${String(this.size)}`;
      }
    }
    const vm = new Diamond();
    activate(vm);
    const parity = vm.parity;
    vm.evaluations = 0;
    const names = hubNames(s, vm);
    vm.n = 3; // parity content unchanged, size changed
    assert.equal(vm.parity, parity, "shallowEqual kept the old instance");
    assert.equal(vm.evaluations, 1);
    assert.deepEqual(names, ["n", "size", "joined"]);
    assert.equal(vm.joined, "odd:3");
  });
});
