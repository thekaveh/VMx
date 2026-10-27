/**
 * Executable form of the ExpandableState owner recipe in
 * docs/content/primitives/state-reactive-helpers.md. The docs-snippet region
 * is shown there verbatim, dedented, and `make docs-check` keeps them equal.
 * No conformance ID (a recipe; EXP-006..008 cover the commands themselves).
 */
import { describe, expect, it } from "vitest";
import {
  ComponentVMBase,
  ExpandableState,
  MessageHub,
  PropertyChangedMessage,
  RxDispatcher,
  ViewModelType,
  type IDispatcher,
  type IMessageHub,
} from "../../src/index.js";

// docs-snippet:start expansion-forwarder
class TreeNodeVM extends ComponentVMBase {
  readonly #expansion = this.own(new ExpandableState());
  // The helper owns its commands; the owner only re-exports them.
  readonly toggleCommand = this.#expansion.toggleExpansionCommand;

  constructor(name: string, hub: IMessageHub, dispatcher: IDispatcher) {
    super({ name, hub, dispatcher });
    // The one-line forwarder: the owner publishes isExpanded (spec 14 rule 6).
    this.own(
      this.#expansion.isExpandedChanged.subscribe(() => this._notifyPropertyChanged("isExpanded")),
    );
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get isExpanded(): boolean {
    return this.#expansion.isExpanded;
  }
}
// docs-snippet:end expansion-forwarder

describe("ExpandableState owner recipe", () => {
  it("publishes isExpanded on the hub and locally for each toggle", () => {
    const hub = new MessageHub();
    const node = new TreeNodeVM("node", hub, RxDispatcher.immediate());
    node.construct();
    const published: string[] = [];
    hub.messages.subscribe((message) => {
      if (message instanceof PropertyChangedMessage && message.sender === node) {
        published.push(message.propertyName);
      }
    });
    const local: string[] = [];
    node.propertyChanged.subscribe((name) => local.push(name));

    node.toggleCommand.execute();
    expect(node.isExpanded).toBe(true);
    node.toggleCommand.execute();
    expect(node.isExpanded).toBe(false);

    expect(published).toEqual(["isExpanded", "isExpanded"]);
    expect(local).toEqual(["isExpanded", "isExpanded"]);
  });

  it("leaves the re-exported command inert after the owner is disposed", () => {
    const node = new TreeNodeVM("node", new MessageHub(), RxDispatcher.immediate());
    node.construct();

    node.dispose();

    expect(node.toggleCommand.canExecute()).toBe(false);
    node.toggleCommand.execute();
    expect(node.isExpanded).toBe(false);
  });
});
