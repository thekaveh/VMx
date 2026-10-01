import { createEffect, createRoot, createSignal, Show } from "solid-js";
import { render } from "solid-js/web";
import { describe, expect, it } from "vitest";
import { PropertyChangedMessage, type ComponentVMOf, type IMessageHub } from "@thekaveh/vmx";
import { NoteView, useVm } from "../src/solid/NoteView";
import type { Note } from "../src/solid/note";
import { constructedVm, countingCommand, countingHub } from "./helpers";

/** Binds `model` in a reactive root and counts effect runs after the first. */
function observe<M>(vm: ComponentVMOf<M>, hub: IMessageHub) {
  let runs = -1;
  let latest: M | undefined;
  const dispose = createRoot((disposeRoot) => {
    const model = useVm(vm, hub, "model");
    createEffect(() => {
      latest = model();
      runs += 1;
    });
    return disposeRoot;
  });
  return { dispose, renders: () => runs, latest: () => latest };
}

describe("Solid recipe (solid-js 1.9.15)", () => {
  it("renders an in-place mutation announced by republishModel once, without replacement", () => {
    const hub = countingHub();
    const note: Note = { title: "draft" };
    const vm = constructedVm(hub, note);
    // Solid delegates `onClick` to the document, so the view must be attached.
    const el = document.body.appendChild(document.createElement("div"));
    const save = countingCommand();
    const disposeView = render(() => <NoteView vm={vm} hub={hub} saveCommand={save.command} />, el);
    const observed = observe(vm, hub);

    note.title = "edited";
    vm.republishModel();

    expect(el.querySelector("h1")?.textContent).toBe("edited");
    expect(observed.renders()).toBe(1);
    expect(vm.model).toBe(note);
    el.querySelector("button")?.click();
    expect(save.runs()).toBe(1);
    disposeView();
    el.remove();
    observed.dispose();
  });

  it("renders a replacement model and a scalar update once each on one subscription", () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "draft" });
    const scalarVm = constructedVm(hub, 1, "count");
    const note = observe(vm, hub);
    const scalar = observe(scalarVm, hub);
    expect(hub.subscriptions).toBe(2);

    vm.model = { title: "replaced" };
    scalarVm.model = 2;

    expect(note.latest()).toEqual({ title: "replaced" });
    expect(note.renders()).toBe(1);
    expect(scalar.latest()).toBe(2);
    expect(scalar.renders()).toBe(1);
    expect(hub.subscriptions).toBe(2);
  });

  it("ignores messages for another sender or another property", () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "draft" });
    const other = constructedVm<Note>(hub, { title: "other" }, "other");
    const observed = observe(vm, hub);

    hub.send(PropertyChangedMessage.create(other, "other", "model"));
    hub.send(PropertyChangedMessage.create(vm, "note", "modeledHint"));

    expect(observed.renders()).toBe(0);
  });

  it("rebinds to another VM when a keyed Show remounts it and releases the first subscription", () => {
    const hub = countingHub();
    const first = constructedVm<Note>(hub, { title: "first" }, "first");
    const second = constructedVm<Note>(hub, { title: "second" }, "second");
    const save = countingCommand();
    const [current, setCurrent] = createSignal(first);
    const el = document.createElement("div");
    const dispose = render(
      () => (
        <Show when={current()} keyed>
          {(vm) => <NoteView vm={vm} hub={hub} saveCommand={save.command} />}
        </Show>
      ),
      el,
    );
    const title = () => el.querySelector("h1")?.textContent;
    expect(title()).toBe("first");

    setCurrent(second);
    expect(title()).toBe("second");
    expect([hub.subscriptions, hub.teardowns]).toEqual([2, 1]);

    first.model = { title: "stale" };
    second.model = { title: "fresh" };
    expect(title()).toBe("fresh");

    dispose();
    expect(hub.teardowns).toBe(2);
  });

  it("stops rendering and releases its subscription on cleanup", () => {
    const hub = countingHub();
    const note: Note = { title: "draft" };
    const vm = constructedVm(hub, note);
    const observed = observe(vm, hub);

    observed.dispose();
    note.title = "late";
    vm.republishModel();

    expect(hub.teardowns).toBe(1);
    expect(observed.renders()).toBe(0);
  });
});
