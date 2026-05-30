import { describe, expect, it, vi } from "vitest";
import {
  hasCapability,
  MessageHub,
  PropertyChangedMessage,
  RxDispatcher,
} from "vmx";

import type { NoteModel } from "../../src/models/noteModel.js";
import { NoteVM } from "../../src/viewmodels/noteVM.js";

function model(over: Partial<NoteModel> = {}): NoteModel {
  return {
    id: "note-01",
    notebookId: "nb-reviews",
    title: "T",
    tags: [],
    body: "B",
    starred: false,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    ...over,
  };
}

function makeVM(overrides: {
  onClose?: (vm: NoteVM) => void;
  onSave?: (vm: NoteVM) => void;
  onDelete?: (vm: NoteVM) => void;
} = {}): { vm: NoteVM; hub: MessageHub } {
  const hub = new MessageHub();
  let builder = NoteVM.builder()
    .name("note:01")
    .model(model())
    .services(hub, RxDispatcher.immediate());
  if (overrides.onClose) builder = builder.onClose(overrides.onClose);
  if (overrides.onSave) builder = builder.onSave(overrides.onSave);
  if (overrides.onDelete) builder = builder.onDelete(overrides.onDelete);
  const vm = builder.build();
  vm.construct();
  return { vm, hub };
}

describe("NoteVM", () => {
  it("declares the documented capability set", () => {
    const { vm } = makeVM();
    for (const cap of [
      "ISelectable",
      "IClosable",
      "IDeletable",
      "ISavable",
      "IReconstructable",
    ] as const) {
      expect(hasCapability(vm, cap)).toBe(true);
    }
  });

  it("close invokes the host callback", () => {
    const onClose = vi.fn();
    const { vm } = makeVM({ onClose });
    expect(vm.canClose()).toBe(true);
    vm.closeCommand.execute();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledWith(vm);
  });

  it("save invokes the host callback only for self-target", () => {
    const onSave = vi.fn();
    const { vm } = makeVM({ onSave });
    const other = NoteVM.builder()
      .name("note:other")
      .model(model({ id: "other" }))
      .services(new MessageHub(), RxDispatcher.immediate())
      .build();
    expect(vm.canSave(vm)).toBe(true);
    expect(vm.canSave(other)).toBe(false);
    vm.save(vm);
    expect(onSave).toHaveBeenCalledTimes(1);
    vm.save(other);
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("delete invokes the host callback", () => {
    const onDelete = vi.fn();
    const { vm } = makeVM({ onDelete });
    vm.deleteCommand.execute();
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("modeled property change publishes title + starred PropertyChangedMessage", () => {
    const { vm, hub } = makeVM();
    const messages: PropertyChangedMessage<unknown>[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage) messages.push(m);
    });
    vm.model = model({ title: "Updated", starred: true });
    const names = messages.map((m) => m.propertyName);
    expect(names).toContain("Model");
    expect(names).toContain("Title");
    expect(names).toContain("Starred");
    expect(vm.title).toBe("Updated");
    expect(vm.starred).toBe(true);
  });

  it("setting the same model reference is a no-op", () => {
    const { vm, hub } = makeVM();
    const messages: PropertyChangedMessage<unknown>[] = [];
    hub.messages.subscribe((m) => {
      if (m instanceof PropertyChangedMessage) messages.push(m);
    });
    vm.model = vm.model;
    expect(messages.length).toBe(0);
  });

  it("close / save / delete are no-ops when no host callback is wired", () => {
    const { vm } = makeVM();
    expect(() => vm.closeCommand.execute()).not.toThrow();
    expect(() => vm.saveCommand.execute()).not.toThrow();
    expect(() => vm.deleteCommand.execute()).not.toThrow();
  });

  it("after dispose, commands are inert", () => {
    const onSave = vi.fn();
    const { vm } = makeVM({ onSave });
    vm.dispose();
    // calling execute on a disposed command silently no-ops
    expect(() => vm.saveCommand.execute()).not.toThrow();
  });

  it("noteId, body, and tags proxy the underlying model", () => {
    const { vm } = makeVM();
    expect(vm.noteId).toBe("note-01");
    expect(vm.body).toBe("B");
    expect(vm.tags).toEqual([]);
  });

  it("builder validates required fields", () => {
    expect(() => NoteVM.builder().build()).toThrow();
  });
});
