import {
  createApp,
  createSSRApp,
  defineComponent,
  effectScope,
  h,
  nextTick,
  onMounted,
  reactive,
  ref,
  shallowRef,
  watch,
  watchEffect,
  type Component,
  type ShallowRef,
} from "vue";
import { renderToString } from "vue/server-renderer";
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

  it("rebinds to another VM when its key changes and releases the first subscription", async () => {
    const hub = countingHub();
    const first = constructedVm<Note>(hub, { title: "first" }, "first");
    const second = constructedVm<Note>(hub, { title: "second" }, "second");
    const save = countingCommand();
    const current = shallowRef(first);
    const el = document.createElement("div");
    const app = createApp({
      render: () =>
        h(NoteView, { key: current.value.name, vm: current.value, hub, saveCommand: save.command }),
    });
    app.mount(el);
    const title = () => el.querySelector("h1")?.textContent;
    expect(title()).toBe("first");

    current.value = second;
    await nextTick();
    expect(title()).toBe("second");
    expect([hub.subscriptions, hub.teardowns]).toEqual([2, 1]);

    first.model = { title: "stale" };
    second.model = { title: "fresh" };
    await nextTick();
    expect(title()).toBe("fresh");

    app.unmount();
    expect(hub.teardowns).toBe(2);
  });

  it("runs the supplied save command", () => {
    const hub = countingHub();
    const view = mountNote(constructedVm<Note>(hub, { title: "draft" }), hub);

    view.el.querySelector("button")?.click();

    expect(view.save.runs()).toBe(1);
  });

  describe("synchronous watchers run once per message", () => {
    function observe<M>(vm: ComponentVMOf<M>, hub: IMessageHub) {
      const counts = { watch: 0, effect: 0 };
      const scope = effectScope();
      scope.run(() => {
        const value = useVm(vm, hub, "model");
        watch(value, () => (counts.watch += 1), { flush: "sync" });
        watchEffect(() => (void value.value, (counts.effect += 1)), { flush: "sync" });
      });
      counts.effect = 0; // drop watchEffect's initial run
      return { scope, counts };
    }

    it("for a replacement model", () => {
      const hub = countingHub();
      const vm = constructedVm<Note>(hub, { title: "draft" });
      const { scope, counts } = observe(vm, hub);

      vm.model = { title: "replaced" };

      expect(counts).toEqual({ watch: 1, effect: 1 });
      scope.stop();
    });

    it("for a scalar change", () => {
      const hub = countingHub();
      const vm = constructedVm(hub, 1, "count");
      const { scope, counts } = observe(vm, hub);

      vm.model = 2;

      expect(counts).toEqual({ watch: 1, effect: 1 });
      scope.stop();
    });

    it("for a same-reference republishModel()", () => {
      const hub = countingHub();
      const note: Note = { title: "draft" };
      const vm = constructedVm(hub, note);
      const { scope, counts } = observe(vm, hub);

      note.title = "edited";
      vm.republishModel();

      expect(counts).toEqual({ watch: 1, effect: 1 });
      scope.stop();
    });
  });

  describe("binds a view-model that reaches it as a Vue proxy", () => {
    function mountHeld(read: () => ComponentVMOf<Note>, hub: IMessageHub) {
      const el = document.createElement("div");
      const app = createApp({
        render: () => h(NoteView, { vm: read(), hub, saveCommand: countingCommand().command }),
      });
      app.mount(el);
      return { app, title: () => el.querySelector("h1")?.textContent };
    }

    async function expectBindsAndUpdates(
      held: ComponentVMOf<Note>,
      raw: ComponentVMOf<Note>,
      hub: IMessageHub,
    ) {
      const view = mountHeld(() => held, hub);
      expect(view.title()).toBe("draft");

      raw.model = { title: "replaced" };
      await nextTick();
      expect(view.title()).toBe("replaced");

      raw.model.title = "edited";
      raw.republishModel();
      await nextTick();
      expect(view.title()).toBe("edited");
      view.app.unmount();
    }

    it("from ref()", async () => {
      const hub = countingHub();
      const vm = constructedVm<Note>(hub, { title: "draft" });
      const held = ref(vm).value as ComponentVMOf<Note>;
      expect(held).not.toBe(vm);

      await expectBindsAndUpdates(held, vm, hub);
    });

    it("from reactive()", async () => {
      const hub = countingHub();
      const vm = constructedVm<Note>(hub, { title: "draft" });
      const held = reactive({ vm }).vm as ComponentVMOf<Note>;
      expect(held).not.toBe(vm);

      await expectBindsAndUpdates(held, vm, hub);
    });

    it("from Options API data()", async () => {
      const hub = countingHub();
      const vm = constructedVm<Note>(hub, { title: "draft" });
      const el = document.createElement("div");
      const app = createApp(
        defineComponent({
          data: () => ({ held: vm }),
          render() {
            return h(NoteView, {
              vm: this.held as ComponentVMOf<Note>,
              hub,
              saveCommand: countingCommand().command,
            });
          },
        }),
      );
      app.mount(el);
      expect(el.querySelector("h1")?.textContent).toBe("draft");

      vm.model = { title: "replaced" };
      await nextTick();
      expect(el.querySelector("h1")?.textContent).toBe("replaced");
      app.unmount();
      expect(hub.teardowns).toBe(1);
    });
  });

  it("throws a TypeError naming the rule when called outside setup() or an effect scope", () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "draft" });

    expect(() => useVm(vm, hub, "model")).toThrowError(
      new TypeError("useVm must be called inside setup() or an effect scope"),
    );
    expect(hub.subscriptions).toBe(0);
  });

  it("releases its subscription when its effect scope stops", () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "draft" });
    const scope = effectScope();
    const value = scope.run(() => useVm(vm, hub, "model"));
    expect([hub.subscriptions, hub.teardowns]).toEqual([1, 0]);

    scope.stop();
    vm.model = { title: "late" };

    expect([hub.subscriptions, hub.teardowns]).toEqual([1, 1]);
    expect(value?.value.title).toBe("draft");
  });

  it("leaves no hub subscription after a server render", async () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "draft" });
    const app = createSSRApp({
      render: () => h(NoteView, { vm, hub, saveCommand: countingCommand().command }),
    });

    const html = await renderToString(app);

    expect(html).toContain("<h1>draft</h1>");
    expect(hub.subscriptions).toBe(hub.teardowns);
    expect(hub.subscriptions).toBe(0);
  });

  it("renders an in-place change announced by a child's setup before the first mount", async () => {
    const hub = countingHub();
    const note: Note = { title: "draft" };
    const vm = constructedVm(hub, note);
    const Child = defineComponent({
      setup() {
        note.title = "edited in child setup";
        vm.republishModel();
        return () => h("i");
      },
    });
    const el = document.createElement("div");
    createApp({
      setup() {
        const model = useVm(vm, hub, "model");
        return () => h("div", [h("h1", model.value.title), h(Child)]);
      },
    }).mount(el);
    await nextTick();

    expect(el.querySelector("h1")?.textContent).toBe("edited in child setup");
  });

  it("subscribes at once when called from a mounted hook", async () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "draft" });
    let model: Readonly<ShallowRef<Note>> | undefined;
    const el = document.createElement("div");
    const app = createApp({
      setup() {
        onMounted(() => {
          model = useVm(vm, hub, "model");
        });
        return () => h("i");
      },
    });
    app.mount(el);
    expect(hub.subscriptions).toBe(1);

    vm.model = { title: "replaced" };
    expect(model?.value.title).toBe("replaced");
    app.unmount();
    expect(hub.teardowns).toBe(1);
  });

  it("does not subscribe for an effect scope stopped before the component mounts", () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "draft" });
    const el = document.createElement("div");
    const app = createApp({
      setup() {
        const scope = effectScope();
        scope.run(() => useVm(vm, hub, "model"));
        scope.stop();
        return () => h("i");
      },
    });
    app.mount(el);
    app.unmount();

    expect([hub.subscriptions, hub.teardowns]).toEqual([0, 0]);
  });
});
