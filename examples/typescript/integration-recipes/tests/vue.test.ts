import { createApp, defineComponent, h, nextTick, type Component } from "vue";
import { describe, expect, it } from "vitest";
import { PropertyChangedMessage, type ComponentVMOf, type IMessageHub } from "@thekaveh/vmx";
import NoteView from "../src/vue/NoteView.vue";
import { useVm } from "../src/vue/composables/useVm";
import type { Note } from "../src/vue/note";
import { constructedVm, countingCommand, countingHub } from "./helpers";

function mount(component: Component, props: Record<string, unknown>) {
  const el = document.createElement("div");
  let updates = 0;
  const app = createApp({
    render: () =>
      h(component, {
        ...props,
        onVnodeUpdated: () => {
          updates += 1;
        },
      }),
  });
  app.mount(el);
  return { el, app, updates: () => updates };
}

function mountNote(vm: ComponentVMOf<Note>, hub: IMessageHub) {
  const save = countingCommand();
  const view = mount(NoteView, { vm, hub, saveCommand: save.command });
  return { ...view, save, title: () => view.el.querySelector("h1")?.textContent };
}

const ValueView = defineComponent({
  props: { vm: { type: Object, required: true }, hub: { type: Object, required: true } },
  setup(props) {
    const value = useVm(props.vm as ComponentVMOf<number>, props.hub as IMessageHub, "model");
    return () => h("span", String(value.value));
  },
});

describe("Vue recipe (vue 3.5.43)", () => {
  it("renders an in-place mutation announced by republishModel once, without replacement", async () => {
    const hub = countingHub();
    const note: Note = { title: "draft" };
    const vm = constructedVm(hub, note);
    const view = mountNote(vm, hub);
    expect(view.title()).toBe("draft");

    note.title = "edited";
    vm.republishModel();
    await nextTick();

    expect(view.title()).toBe("edited");
    expect(view.updates()).toBe(1);
    expect(vm.model).toBe(note);
  });

  it("renders a replacement model and a scalar update once each on one subscription", async () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "draft" });
    const view = mountNote(vm, hub);
    const scalarVm = constructedVm(hub, 1, "count");
    const scalar = mount(ValueView, { vm: scalarVm, hub });
    expect(hub.subscriptions).toBe(2);

    vm.model = { title: "replaced" };
    scalarVm.model = 2;
    await nextTick();

    expect(view.title()).toBe("replaced");
    expect(view.updates()).toBe(1);
    expect(scalar.el.textContent).toBe("2");
    expect(scalar.updates()).toBe(1);
    expect(hub.subscriptions).toBe(2);
  });

  it("ignores messages for another sender or another property", async () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "draft" });
    const other = constructedVm<Note>(hub, { title: "other" }, "other");
    const view = mountNote(vm, hub);

    hub.send(PropertyChangedMessage.create(other, "other", "model"));
    hub.send(PropertyChangedMessage.create(vm, "note", "modeledHint"));
    await nextTick();

    expect(view.updates()).toBe(0);
  });

  it("stops rendering and releases its subscription on unmount", async () => {
    const hub = countingHub();
    const note: Note = { title: "draft" };
    const vm = constructedVm(hub, note);
    const view = mountNote(vm, hub);

    view.app.unmount();
    note.title = "late";
    vm.republishModel();
    await nextTick();

    expect(hub.teardowns).toBe(1);
    expect(view.updates()).toBe(0);
    expect(view.el.innerHTML).toBe("");
  });

  it("runs the supplied save command", () => {
    const hub = countingHub();
    const view = mountNote(constructedVm<Note>(hub, { title: "draft" }), hub);

    view.el.querySelector("button")?.click();

    expect(view.save.runs()).toBe(1);
  });
});
