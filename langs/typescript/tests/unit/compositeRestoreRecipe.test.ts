/**
 * Executable form of the restore-the-current-child recipe in
 * docs/content/primitives/viewmodel-families/composite-family.md. The
 * docs-snippet region is shown there verbatim, dedented, and
 * `make docs-check` keeps them equal. Spec 06 §3.2 and ADR-0158 state the
 * behavior; COMP-025 covers the selector re-run. No conformance ID (recipe;
 * #659).
 */
import { describe, expect, it } from "vitest";
import {
  ComponentVM,
  CompositeVM,
  MessageHub,
  RxDispatcher,
  type IDispatcher,
  type IMessageHub,
} from "../../src/index.js";

function makeTab(name: string, hub: IMessageHub, dispatcher: IDispatcher): ComponentVM {
  return ComponentVM.builder().name(name).services(hub, dispatcher).build();
}

describe("restore the current child recipe", () => {
  it("restores the last selection after destruct and after reconstruct", () => {
    const hub = new MessageHub();
    const dispatcher = RxDispatcher.immediate();
    const home = makeTab("home", hub, dispatcher);
    const settings = makeTab("settings", hub, dispatcher);

    // docs-snippet:start restore-current
    let lastCurrent: ComponentVM | null = null;
    const tabs = CompositeVM.builder<ComponentVM>()
      .name("tabs")
      .services(hub, dispatcher)
      .children(() => [home, settings])
      // Destruct reports null. Record only a real selection.
      .onCurrentChanged((tab) => {
        if (tab !== null) lastCurrent = tab;
      })
      // Runs on every construct, including reconstruct().
      .current(() => lastCurrent)
      .build();
    // docs-snippet:end restore-current

    tabs.construct();
    expect(tabs.current, "nothing to restore on the first construct").toBeNull();

    tabs.selectComponent(settings);
    tabs.destruct();
    expect(tabs.current, "destruct clears current (COMP-005)").toBeNull();
    tabs.construct();
    expect(tabs.current).toBe(settings);
    expect(settings.isCurrent).toBe(true);

    tabs.selectComponent(home);
    tabs.reconstruct();
    expect(tabs.current).toBe(home);
    expect(home.isCurrent).toBe(true);

    // A child that is no longer contained is a silent no-op (spec 06 §3.2).
    tabs.removeAt(0);
    tabs.destruct();
    tabs.construct();
    expect(tabs.current).toBeNull();

    tabs.dispose();
  });

  it("does not restore when the recorder also keeps the null from destruct", () => {
    const hub = new MessageHub();
    const dispatcher = RxDispatcher.immediate();
    const home = makeTab("home", hub, dispatcher);
    const settings = makeTab("settings", hub, dispatcher);

    let lastCurrent: ComponentVM | null = null;
    const tabs = CompositeVM.builder<ComponentVM>()
      .name("tabs")
      .services(hub, dispatcher)
      .children(() => [home, settings])
      .onCurrentChanged((tab) => {
        lastCurrent = tab;
      })
      .current(() => lastCurrent)
      .build();

    tabs.construct();
    tabs.selectComponent(settings);
    tabs.destruct();
    expect(lastCurrent).toBeNull();
    tabs.construct();
    expect(tabs.current).toBeNull();

    tabs.selectComponent(home);
    tabs.reconstruct();
    expect(tabs.current).toBeNull();

    tabs.dispose();
  });
});
