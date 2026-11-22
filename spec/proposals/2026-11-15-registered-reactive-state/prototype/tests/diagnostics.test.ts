/**
 * R19.* development diagnostics: the staleness check, the unpublished-getter probe, hand-written notifications of
 * registered names, and explain().
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ComponentVM } from "@thekaveh/vmx";
import { activate, configureReactiveDiagnostics, explain } from "../src/index.js";
import { base, captureReports, type Services, services, tick } from "./support.js";

class Listing extends ComponentVM {
  declare readonly wide: boolean;
  readonly write;
  #untrackedCount = 0;
  constructor(s: Services) {
    super(base(s, "listing"));
    this.write = this.observable({ wide: false });
    this.computed("totalText", "widthText");
  }
  /** A computed over a plain #field that changes: stale without invalidate (R19.1). */
  get totalText(): string {
    return `${String(this.#untrackedCount)} items`;
  }
  get widthText(): string {
    return this.wide ? "Narrow" : "Widen";
  }
  /** Bound by a view but not registered: it never announces (R19.2). */
  get widthHint(): string {
    return this.wide ? "wide" : "narrow";
  }
  add(): void {
    this.#untrackedCount += 1;
  }
  shout(): void {
    this._notifyPropertyChanged("widthText");
  }
}

describe("R19.* development diagnostics", () => {
  // Fix round 1 (R19.1, R19.2): the staleness check and the probe run on a later task, never inside a read or
  // an activation, so these tests wait one task before they look at the reports.
  it("R19.1 reports a computed that changed without a tracked dependency, once per class and name", async () => {
    const reports = captureReports();
    const vm = new Listing(services());
    activate(vm);
    assert.equal(vm.totalText, "0 items");
    vm.add();
    assert.equal(vm.totalText, "0 items", "the memoized value is returned");
    vm.add();
    void vm.totalText;
    assert.equal(reports.length, 0, "no diagnostic runs inside a read");
    await tick();
    assert.deepEqual(
      reports.filter((report) => report.includes("totalText")),
      ["Listing.totalText changed without a tracked dependency"],
    );
  });

  it("R19.2 reports a public getter that reads reactive state but is not published", async () => {
    const reports = captureReports();
    activate(new Listing(services()));
    await tick();
    assert.ok(reports.some((report) => report.startsWith("Listing.widthHint reads reactive state but is not published")));
    assert.ok(!reports.some((report) => report.startsWith("Listing.widthText reads")));
  });

  it("R19.3 reports a hand-written notification of a registered name", () => {
    const reports = captureReports();
    const vm = new Listing(services());
    vm.shout();
    vm.shout();
    assert.equal(reports.filter((report) => report.includes("hand-written")).length, 1);
  });

  it("R19.4 explain lists the nodes read by the last evaluation", () => {
    const vm = new Listing(services());
    activate(vm);
    assert.deepEqual(
      explain(vm, "widthText").map((entry) => entry.name),
      ["wide"],
    );
    assert.deepEqual(explain(vm, "totalText"), []);
  });

  it("diagnostics change no behavior and are off in production", () => {
    configureReactiveDiagnostics({ development: false });
    try {
      const reports = captureReports();
      const vm = new Listing(services());
      activate(vm);
      vm.add();
      void vm.totalText;
      vm.shout();
      assert.deepEqual(reports, []);
    } finally {
      configureReactiveDiagnostics({ development: undefined });
    }
  });
});
