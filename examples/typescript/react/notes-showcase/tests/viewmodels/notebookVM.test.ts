import { describe, expect, it } from "vitest";
import {
  hasCapability,
  MessageHub,
  PropertyChangedMessage,
  RxDispatcher,
  type IMessage,
} from "vmx";

import type { NotebookModel } from "../../src/models/notebookModel.js";
import { NotebookVM } from "../../src/viewmodels/notebookVM.js";

function makeVM(overrides: Partial<NotebookModel> = {}): {
  vm: NotebookVM;
  hub: MessageHub;
} {
  const hub = new MessageHub();
  const dispatcher = RxDispatcher.immediate();
  const model: NotebookModel = {
    id: "nb-test",
    name: "Test",
    parentId: null,
    ...overrides,
  };
  const vm = NotebookVM.builder()
    .name("nb:test")
    .model(model)
    .services(hub, dispatcher)
    .build();
  return { vm, hub };
}

describe("NotebookVM", () => {
  it("declares the documented capability set", () => {
    const { vm } = makeVM();
    for (const cap of [
      "ISelectable",
      "IExpandable",
      "ICollapsible",
      "IExpansionTogglable",
      "IReconstructable",
    ] as const) {
      expect(hasCapability(vm, cap)).toBe(true);
    }
  });

  it("toggleExpansion publishes PropertyChangedMessage('isExpanded')", () => {
    const { vm, hub } = makeVM();
    vm.construct();
    const messages: IMessage[] = [];
    hub.messages.subscribe((m) => messages.push(m));

    expect(vm.isExpanded).toBe(false);
    vm.toggleExpansion();
    expect(vm.isExpanded).toBe(true);

    const propMessages = messages.filter(
      (m) =>
        m instanceof PropertyChangedMessage && m.propertyName === "isExpanded",
    );
    expect(propMessages.length).toBeGreaterThan(0);
  });

  it("expand and collapse are idempotent", () => {
    const { vm } = makeVM();
    expect(vm.canExpand()).toBe(true);
    vm.expand();
    expect(vm.isExpanded).toBe(true);
    expect(vm.canExpand()).toBe(false);
    vm.expand();
    expect(vm.isExpanded).toBe(true);
    expect(vm.canCollapse()).toBe(true);
    vm.collapse();
    expect(vm.isExpanded).toBe(false);
    vm.collapse();
    expect(vm.isExpanded).toBe(false);
  });

  it("setting model emits PropertyChangedMessage for model + notebookName", () => {
    const { vm, hub } = makeVM({ name: "Old" });
    const messages: PropertyChangedMessage<unknown>[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage) messages.push(m);
    });
    vm.model = { id: "nb-test", name: "New", parentId: null };
    expect(vm.notebookName).toBe("New");
    const names = messages.map((m) => m.propertyName).sort();
    expect(names).toContain("Model");
    expect(names).toContain("NotebookName");
  });

  it("setting the same model reference is a no-op", () => {
    const { vm, hub } = makeVM();
    const messages: PropertyChangedMessage<unknown>[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage) messages.push(m);
    });
    const same = vm.model;
    vm.model = same;
    expect(messages.length).toBe(0);
  });

  it("dispose disposes the expansion state without throwing", () => {
    const { vm } = makeVM();
    vm.construct();
    vm.dispose();
    // After dispose, calling expand should not throw — expansion is dormant.
    expect(() => vm.toggleExpansion()).not.toThrow();
  });

  it("initiallyExpanded(true) starts expanded", () => {
    const hub = new MessageHub();
    const vm = NotebookVM.builder()
      .name("nb:exp")
      .model({ id: "nb-exp", name: "Exp", parentId: null })
      .services(hub, RxDispatcher.immediate())
      .initiallyExpanded(true)
      .build();
    expect(vm.isExpanded).toBe(true);
  });

  it("builder validates required fields", () => {
    const hub = new MessageHub();
    expect(() => NotebookVM.builder().build()).toThrow();
    expect(() =>
      NotebookVM.builder().name("x").services(hub, RxDispatcher.immediate()).build(),
    ).toThrow(/model/);
    expect(() =>
      NotebookVM.builder()
        .name("x")
        .model({ id: "i", name: "n", parentId: null })
        .build(),
    ).toThrow(/services/);
  });
});
