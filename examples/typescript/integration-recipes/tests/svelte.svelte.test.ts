// Runes are enabled in this module (`.svelte.` infix) so tests can change
// component inputs through a `$state` props object.
import { flushSync, mount, unmount, type Component } from "svelte";
import { describe, expect, it } from "vitest";
import type { Observable } from "rxjs";
import type { ComponentVMOf, ICommand, IMessage, IMessageHub } from "@thekaveh/vmx";
import NoteView from "../src/svelte/NoteView.svelte";
import NoteViewRunes from "../src/svelte/NoteViewRunes.svelte";
import type { Note } from "../src/svelte/note";
import { constructedVm, countingCommand, countingHub } from "./helpers";

type Inputs = {
  vm: ComponentVMOf<Note>;
  hub: IMessageHub;
  saveCommand: ICommand;
};

function render(component: Component<Record<string, unknown>>, initial: Inputs) {
  const target = document.createElement("div");
  document.body.append(target);
  const props = $state(initial);
  const instance = mount(component, { target, props });
  flushSync();
  return {
    props,
    title: () => target.querySelector("h1")?.textContent,
    click: () => target.querySelector("button")?.click(),
    destroy: () => {
      void unmount(instance);
      target.remove();
    },
  };
}

const VARIANTS = [
  ["store component", NoteView],
  ["runes component", NoteViewRunes],
] as const;

describe.each(VARIANTS)("Svelte %s (svelte 5.57.1)", (_, component) => {
  it("renders an in-place mutation announced by republishModel", () => {
    const hub = countingHub();
    const note: Note = { title: "draft" };
    const vm = constructedVm(hub, note);
    const view = render(component, { vm, hub, saveCommand: countingCommand().command });
    expect(view.title()).toBe("draft");

    note.title = "edited";
    vm.republishModel();
    flushSync();

    expect(view.title()).toBe("edited");
    expect(vm.model).toBe(note);
    view.destroy();
  });

  it("shows a change made between mount and the effect flush", () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "draft" });
    const target = document.createElement("div");
    const instance = mount(component, {
      target,
      props: { vm, hub, saveCommand: countingCommand().command },
    });

    vm.model = { title: "before flush" };
    flushSync();

    expect(target.querySelector("h1")?.textContent).toBe("before flush");
    void unmount(instance);
  });

  it("moves its subscription when the vm or hub input changes", () => {
    const firstHub = countingHub();
    const first = constructedVm<Note>(firstHub, { title: "first" });
    const view = render(component, {
      vm: first,
      hub: firstHub,
      saveCommand: countingCommand().command,
    });
    expect(firstHub.subscriptions).toBe(1);

    const secondHub = countingHub();
    const second = constructedVm<Note>(secondHub, { title: "second" }, "second");
    view.props.vm = second;
    view.props.hub = secondHub;
    flushSync();

    expect(view.title()).toBe("second");
    expect(firstHub.teardowns).toBe(1);
    expect(secondHub.subscriptions).toBe(1);

    first.model = { title: "stale" };
    second.model = { title: "current" };
    flushSync();
    expect(view.title()).toBe("current");
    view.destroy();
  });

  it("releases its subscription on destroy", () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "draft" });
    const view = render(component, { vm, hub, saveCommand: countingCommand().command });

    view.destroy();
    vm.model = { title: "late" };

    expect(hub.subscriptions).toBe(1);
    expect(hub.teardowns).toBe(1);
  });

  it("surfaces a hub that cannot be subscribed", () => {
    const failure = new Error("hub unavailable");
    const brokenHub: IMessageHub = {
      get messages(): Observable<IMessage> {
        throw failure;
      },
      send: () => {},
    };
    const target = document.createElement("div");

    expect(() => {
      mount(component, {
        target,
        props: {
          vm: constructedVm<Note>(countingHub(), { title: "draft" }),
          hub: brokenHub,
          saveCommand: countingCommand().command,
        },
      });
      flushSync();
    }).toThrow(failure);
  });

  it("runs the supplied save command", () => {
    const hub = countingHub();
    const save = countingCommand();
    const view = render(component, {
      vm: constructedVm<Note>(hub, { title: "draft" }),
      hub,
      saveCommand: save.command,
    });

    view.click();

    expect(save.runs()).toBe(1);
    view.destroy();
  });
});
