/**
 * Executable form of the leaf-VM member recipe: a component that owns member
 * VMs, transitions them from its own lifecycle hooks with
 * `_transitionChildren`, and disposes them first through `ownMember`. The
 * docs-snippet region is shown in the docs verbatim, dedented, and
 * `make docs-check` keeps them equal. Spec 02 §6.1 and §7.1 and ADR-0162
 * state the behavior; LIFE-016..LIFE-020 cover it. No conformance ID
 * (recipe; #661).
 */
import { describe, expect, it } from "vitest";
import {
  ComponentVM,
  ComponentVMBase,
  ConstructionStatus,
  ConstructionStatusChangedMessage,
  MessageHub,
  RxDispatcher,
  ViewModelType,
} from "../../src/index.js";

// docs-snippet:start leaf-member-children
class PanelVM extends ComponentVMBase {
  // Members: disposed with the panel, before the panel publishes Disposed.
  readonly chart = this.ownMember(this.#member("chart"));
  readonly table = this.ownMember(this.#member("table"));

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get #members(): ComponentVMBase[] {
    return [this.chart, this.table];
  }

  protected override _onConstruct(): void {
    super._onConstruct();
    // The panel publishes Constructed after both members constructed.
    this._transitionChildren(this.#members, true);
  }

  protected override _onDestruct(): void {
    // Reverse order; the panel's own destruct hook runs last.
    this._transitionChildren([...this.#members].reverse(), false, () => super._onDestruct());
  }

  #member(name: string): ComponentVM {
    return ComponentVM.builder().name(name).services(this.hub, this._dispatcher).build();
  }
}
// docs-snippet:end leaf-member-children

function setup() {
  const hub = new MessageHub();
  const log: string[] = [];
  hub.messages.subscribe((message) => {
    if (message instanceof ConstructionStatusChangedMessage) {
      log.push(`${message.senderName}:${ConstructionStatus[message.status]}`);
    }
  });
  const panel = new PanelVM({ name: "panel", hub, dispatcher: RxDispatcher.immediate() });
  return { panel, log };
}

describe("leaf member children recipe", () => {
  it("constructs the members in order before the panel settles", () => {
    const { panel, log } = setup();

    panel.construct();

    expect(panel.chart.status).toBe(ConstructionStatus.Constructed);
    expect(panel.table.status).toBe(ConstructionStatus.Constructed);
    expect(log).toEqual([
      "panel:Constructing",
      "chart:Constructing",
      "chart:Constructed",
      "table:Constructing",
      "table:Constructed",
      "panel:Constructed",
    ]);
  });

  it("destructs the members in reverse order before the panel settles", () => {
    const { panel, log } = setup();
    panel.construct();
    log.length = 0;

    panel.destruct();

    expect(log).toEqual([
      "panel:Destructing",
      "table:Destructing",
      "table:Destructed",
      "chart:Destructing",
      "chart:Destructed",
      "panel:Destructed",
    ]);
  });

  it("disposes the members before the panel", () => {
    const { panel, log } = setup();
    panel.construct();
    log.length = 0;

    panel.dispose();

    expect(log).toEqual(["chart:Disposed", "table:Disposed", "panel:Disposed"]);
  });
});
