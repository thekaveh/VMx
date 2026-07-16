import { describe, expect, it } from "vitest";
import {
  type IAsyncCommand,
  MessageHub,
  RxDispatcher,
  TreeStructureChangedMessage,
  type IMessage,
} from "@thekaveh/vmx";

import { InMemoryNoteRepository } from "../../src/models/inMemoryRepository.js";
import { buildSeed } from "../../src/models/seed.js";
import { NotebooksRootVM } from "../../src/viewmodels/notebooksRootVM.js";

function makeRoot(): { vm: NotebooksRootVM; hub: MessageHub; repo: InMemoryNoteRepository } {
  const hub = new MessageHub();
  const repo = new InMemoryNoteRepository(buildSeed(), {
    loadAllDelayMs: 0,
    addNotebookDelayMs: 0,
  });
  const vm = NotebooksRootVM.builder()
    .name("notebooks")
    .services(hub, RxDispatcher.immediate())
    .repository(repo)
    .build();
  vm.construct();
  return { vm, hub, repo };
}

describe("NotebooksRootVM", () => {
  it("populateAsync loads the seed and exposes roots / walk", async () => {
    const { vm } = makeRoot();
    await vm.populateAsync();
    expect(vm.all.length).toBe(5);
    expect(vm.roots.length).toBe(4);
    expect([...vm.walk()].length).toBe(5);
  });

  it("childrenOf returns nested notebooks", async () => {
    const { vm } = makeRoot();
    await vm.populateAsync();
    const work = vm.all.find((n) => n.model.id === "nb-work");
    expect(work).toBeDefined();
    const kids = vm.childrenOf(work!);
    expect(kids.length).toBe(1);
    expect(kids[0]?.model.id).toBe("nb-specs");
  });

  it("setting current emits PropertyChangedMessage and equality-guards", async () => {
    const { vm, hub } = makeRoot();
    await vm.populateAsync();
    const messages: IMessage[] = [];
    hub.messages.subscribe((m) => messages.push(m));
    const [first] = vm.roots;
    vm.current = first ?? null;
    const before = messages.length;
    vm.current = first ?? null; // no-op
    expect(messages.length).toBe(before);
    expect(vm.current).toBe(first);
  });

  it("addNotebookAsync emits TreeStructureChangedMessage('added')", async () => {
    const { vm, hub } = makeRoot();
    await vm.populateAsync();
    const events: TreeStructureChangedMessage<unknown, unknown>[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof TreeStructureChangedMessage) events.push(m);
    });
    await vm.addNotebookAsync(null, "Fresh");
    expect(vm.all.length).toBe(6);
    expect(events.some((e) => e.change === "added")).toBe(true);
  });

  it("canCreateNew false until constructed and after destruct", () => {
    const hub = new MessageHub();
    const repo = new InMemoryNoteRepository(buildSeed());
    const vm = NotebooksRootVM.builder()
      .name("nb-root")
      .services(hub, RxDispatcher.immediate())
      .repository(repo)
      .build();
    expect(vm.canCreateNew()).toBe(false);
    vm.construct();
    expect(vm.canCreateNew()).toBe(true);
    vm.destruct();
    expect(vm.canCreateNew()).toBe(false);
  });

  it("createNew triggers an addNotebook via the command", async () => {
    const { vm, repo } = makeRoot();
    await vm.populateAsync();
    const before = vm.all.length;
    await (vm.addNotebookCommand as IAsyncCommand).executeAsync();
    expect(vm.all.length).toBe(before + 1);
    void repo;
  });

  it("populateAsync replaces (and disposes) previous children", async () => {
    const { vm } = makeRoot();
    await vm.populateAsync();
    const prev = vm.all[0];
    await vm.populateAsync();
    expect(prev).not.toBe(vm.all[0]);
    expect(vm.all.length).toBe(5);
  });

  it("dispose cleans up children", async () => {
    const { vm } = makeRoot();
    await vm.populateAsync();
    expect(() => vm.dispose()).not.toThrow();
  });

  it("builder validates required fields", () => {
    expect(() => NotebooksRootVM.builder().build()).toThrow();
  });
});
