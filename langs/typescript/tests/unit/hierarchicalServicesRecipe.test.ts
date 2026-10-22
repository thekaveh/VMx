/**
 * Executable form of the "pass services to children" recipe in
 * docs/content/primitives/viewmodel-families/hierarchical-family.md. The
 * docs-snippet region is shown there verbatim, dedented, and `make docs-check`
 * keeps them equal. No conformance ID (recipe; ADR-0009, #665).
 */
import { describe, expect, it } from "vitest";
import {
  HierarchicalVM,
  MessageHub,
  RxDispatcher,
  TreeStructureChangedMessage,
  type IDispatcher,
  type IMessage,
  type IMessageHub,
} from "../../src/index.js";

// docs-snippet:start hierarchical-services
interface NavItem {
  title: string;
  children: NavItem[];
}

class NavNodeVM extends HierarchicalVM<NavItem, NavNodeVM> {
  constructor(model: NavItem, hub: IMessageHub, dispatcher: IDispatcher) {
    super({
      model,
      hub,
      dispatcher,
      // Each child gets the same services, so its messages reach `hub`.
      childrenFactory: (parent) =>
        parent.model.children.map((item) => new NavNodeVM(item, hub, dispatcher)),
    });
  }
}
// docs-snippet:end hierarchical-services

const item = (title: string, children: NavItem[] = []): NavItem => ({ title, children });

describe("hierarchical services recipe", () => {
  it("publishes a descendant's tree changes on the application hub", () => {
    const appHub = new MessageHub();
    const seen: IMessage[] = [];
    appHub.messages.subscribe((message) => seen.push(message));
    const root = new NavNodeVM(
      item("root", [item("docs", [item("drafts")])]),
      appHub,
      RxDispatcher.immediate(),
    );

    const [docs] = root.children;
    const [drafts] = docs?.children ?? [];
    docs?.addChild(new NavNodeVM(item("archive"), appHub, RxDispatcher.immediate()));

    expect(docs?.hub).toBe(appHub);
    expect(drafts?.hub).toBe(appHub);
    expect(
      seen.some((m) => m instanceof TreeStructureChangedMessage && m.sender === docs),
    ).toBe(true);
  });

  it("without services, a node publishes on a private hub instead", () => {
    const appHub = new MessageHub();
    const seen: IMessage[] = [];
    appHub.messages.subscribe((message) => seen.push(message));
    class LooseNodeVM extends HierarchicalVM<NavItem, LooseNodeVM> {}
    const loose = new LooseNodeVM({ model: item("loose"), childrenFactory: () => [] });
    const privateMessages: IMessage[] = [];
    loose.hub.messages.subscribe((message) => privateMessages.push(message));

    loose.addChild(new LooseNodeVM({ model: item("child"), childrenFactory: () => [] }));

    expect(loose.hub).not.toBe(appHub);
    expect(privateMessages.some((m) => m instanceof TreeStructureChangedMessage)).toBe(true);
    expect(seen).toEqual([]);
  });
});
