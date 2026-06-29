/**
 * VMX-104 regression — the selectNext / selectPrevious placeholder commands
 * wire the status trigger, so their canExecuteChanged fires on lifecycle
 * transitions (matching C#/Python/Swift). Previously the TS leaf base built them
 * with `.predicate(() => false)` and NO `.triggers(...)`, leaving a bound view's
 * next/previous affordance permanently stale.
 */
import { describe, expect, it } from "vitest";
import {
  ComponentVM,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";

describe("VMX-104: selectNext/selectPrevious emit canExecuteChanged on status change", () => {
  it("fires canExecuteChanged when the VM lifecycle transitions", () => {
    const hub = new MessageHub();
    const disp = RxDispatcher.immediate();
    const vm = ComponentVM.builder().name("leaf").services(hub, disp).build();

    let nextChanges = 0;
    let prevChanges = 0;
    vm.selectNextCommand.canExecuteChanged.subscribe(() => nextChanges++);
    vm.selectPreviousCommand.canExecuteChanged.subscribe(() => prevChanges++);

    vm.construct(); // Constructing → Constructed: two status-trigger emissions

    expect(nextChanges, "selectNext canExecuteChanged must fire on status change").toBeGreaterThan(0);
    expect(prevChanges, "selectPrevious canExecuteChanged must fire on status change").toBeGreaterThan(0);

    // canExecute remains false on a leaf (no sibling navigation slot) — only the
    // change signal was missing.
    expect(vm.selectNextCommand.canExecute()).toBe(false);
    expect(vm.selectPreviousCommand.canExecute()).toBe(false);

    vm.dispose();
  });
});
