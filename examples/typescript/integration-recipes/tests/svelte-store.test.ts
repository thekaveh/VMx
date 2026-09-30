import { Observable, Subject, config } from "rxjs";
import { get } from "svelte/store";
import { afterEach, describe, expect, it } from "vitest";
import { MessageHub, PropertyChangedMessage, type IMessage, type IMessageHub } from "@thekaveh/vmx";
import type { Note } from "../src/svelte/note";
import { vmStore } from "../src/svelte/vmStore";
import { constructedVm, countingHub } from "./helpers";

function record<T>(store: { subscribe(run: (value: T) => void): () => void }) {
  const values: T[] = [];
  const unsubscribe = store.subscribe((value) => values.push(value));
  return { values, unsubscribe };
}

const titles = (values: Note[]) => values.map((note) => note.title);

afterEach(() => {
  config.onUnhandledError = null;
});

describe("Svelte store recipe (svelte 5.57.1)", () => {
  it("delivers a change made before the first subscriber at once", () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "draft" });
    const store = vmStore(vm, hub, "model");

    vm.model = { title: "unobserved" };
    const first = record(store);

    expect(titles(first.values)).toEqual(["unobserved"]);
    first.unsubscribe();
  });

  it("delivers a replacement made between disconnect and reconnect without another change", () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "draft" });
    const store = vmStore(vm, hub, "model");
    const first = record(store);
    first.unsubscribe();
    expect(hub.teardowns).toBe(1);

    const replacement = { title: "replaced while idle" };
    vm.model = replacement;
    const second = record(store);

    expect(second.values).toEqual([replacement]);
    expect(get(store)).toBe(replacement);
    second.unsubscribe();
  });

  it("emits an in-place mutation announced by republishModel", () => {
    const hub = countingHub();
    const note: Note = { title: "draft" };
    const vm = constructedVm(hub, note);
    const subscriber = record(vmStore(vm, hub, "model"));

    note.title = "edited";
    vm.republishModel();

    expect(subscriber.values).toEqual([note, note]);
    expect(note.title).toBe("edited");
    subscriber.unsubscribe();
  });

  it("ignores messages for another sender or another property", () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "draft" });
    const other = constructedVm<Note>(hub, { title: "other" }, "other");
    const subscriber = record(vmStore(vm, hub, "model"));

    hub.send(PropertyChangedMessage.create(other, "other", "model"));
    hub.send(PropertyChangedMessage.create(vm, "note", "modeledHint"));

    expect(subscriber.values).toHaveLength(1);
    subscriber.unsubscribe();
  });

  it("shares one hub subscription and releases it after the last subscriber", () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "draft" });
    const store = vmStore(vm, hub, "model");

    const first = record(store);
    const second = record(store);
    expect(hub.subscriptions).toBe(1);

    vm.model = { title: "shared" };
    expect(titles(first.values)).toEqual(["draft", "shared"]);
    expect(titles(second.values)).toEqual(["draft", "shared"]);

    first.unsubscribe();
    expect(hub.teardowns).toBe(0);
    second.unsubscribe();
    expect(hub.teardowns).toBe(1);

    vm.model = { title: "after release" };
    expect(titles(second.values)).toEqual(["draft", "shared"]);
  });

  it("keeps the latest value for changes around attachment", () => {
    const inner = new MessageHub();
    const vm = constructedVm<Note>(inner, { title: "draft" });
    // Changes the VM after the hub subscription is live but before the
    // store's catch-up read, the narrowest window during attachment.
    const racingHub: IMessageHub = {
      messages: new Observable<IMessage>((subscriber) => {
        const subscription = inner.messages.subscribe(subscriber);
        vm.model = { title: "during attach" };
        return subscription;
      }),
      send: (message) => inner.send(message),
    };
    const store = vmStore(vm, racingHub, "model");

    vm.model = { title: "before attach" };
    const subscriber = record(store);
    vm.model = { title: "after attach" };

    expect(titles(subscriber.values)).toEqual(["during attach", "after attach"]);
    expect(get(store).title).toBe("after attach");
    subscriber.unsubscribe();
  });

  it("surfaces a failed catch-up read and releases the hub subscription", () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "draft" });
    const store = vmStore(vm, hub, "model");
    const failure = new Error("model unavailable");
    Object.defineProperty(vm, "model", {
      get: () => {
        throw failure;
      },
    });

    expect(() => store.subscribe(() => {})).toThrow(failure);
    expect(hub.subscriptions).toBe(1);
    expect(hub.teardowns).toBe(1);
  });

  it("surfaces a hub that cannot be subscribed without registering a listener", () => {
    const vm = constructedVm<Note>(new MessageHub(), { title: "draft" });
    const failure = new Error("hub unavailable");
    const brokenHub: IMessageHub = {
      get messages(): Observable<IMessage> {
        throw failure;
      },
      send: () => {},
    };

    expect(() => vmStore(vm, brokenHub, "model").subscribe(() => {})).toThrow(failure);
  });

  it("reports a hub error to RxJS, releases the listener and keeps the last value", () => {
    const reported: unknown[] = [];
    config.onUnhandledError = (error) => reported.push(error);
    const stream = new Subject<IMessage>();
    const hub = countingHub({ messages: stream, send: (message) => stream.next(message) });
    const vm = constructedVm<Note>(new MessageHub(), { title: "draft" });
    const store = vmStore(vm, hub, "model");
    const subscriber = record(store);
    const failure = new Error("hub failed");

    stream.error(failure);

    return new Promise<void>((resolve) => {
      setTimeout(() => {
        expect(reported).toEqual([failure]);
        expect(hub.teardowns).toBe(1);
        expect(titles(subscriber.values)).toEqual(["draft"]);
        subscriber.unsubscribe();
        resolve();
      });
    });
  });

  it("keeps the last value when the hub is disposed", () => {
    const inner = new MessageHub();
    const hub = countingHub(inner);
    const vm = constructedVm<Note>(inner, { title: "draft" });
    const subscriber = record(vmStore(vm, hub, "model"));

    inner.dispose();

    expect(hub.teardowns).toBe(1);
    expect(titles(subscriber.values)).toEqual(["draft"]);
    subscriber.unsubscribe();
  });

  it("shows a disposed VM's retained model and nothing after it", () => {
    const hub = countingHub();
    const vm = constructedVm<Note>(hub, { title: "retained" });
    const store = vmStore(vm, hub, "model");
    vm.dispose();

    const subscriber = record(store);
    vm.model = { title: "ignored" };

    expect(titles(subscriber.values)).toEqual(["retained"]);
    subscriber.unsubscribe();
    expect(hub.teardowns).toBe(hub.subscriptions);
  });
});
