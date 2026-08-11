import { StrictMode, useInsertionEffect, type JSX } from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { BehaviorSubject, Observable, Subject } from "rxjs";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  AsyncResourceStatus,
  AsyncResourceVM,
  ComponentVM,
  ComponentVMOf,
  CompositeVM,
  DerivedProperty,
  FormVM,
  MessageHub,
  NullDispatcher,
  ObservableList,
  PropertyChangedMessage,
  RelayCommand,
  type IMessage,
  type IMessageHub,
} from "@thekaveh/vmx";

import {
  createVmxStore,
  shallowEqual,
  useAsyncResource,
  useCommand,
  useDerivedProperty,
  useObservableList,
  useVm,
  useVmCollection,
  useVmx,
} from "../src/index.js";

afterEach(cleanup);

function modeled(hub: IMessageHub, model = 0): ComponentVMOf<number> {
  return ComponentVMOf.create({
    name: "value",
    hub,
    dispatcher: NullDispatcher.INSTANCE,
    model,
  });
}

describe("createVmxStore and useVmx", () => {
  it("updates snapshots synchronously, coalesces notification, and disposes idempotently", async () => {
    const hub = new MessageHub();
    const store = createVmxStore(hub);
    const subscribe = store.subscribe;
    const initial = store.getSnapshot();
    expect(store.getSnapshot()).toBe(initial);
    expect(store.getServerSnapshot()).toBe(initial);
    const notify = vi.fn();
    const unsubscribe = subscribe(notify);
    expect(store.getSnapshot()).toBe(initial + 1);

    hub.send(PropertyChangedMessage.create({}, "test", "value"));
    expect(store.getSnapshot()).toBe(initial + 2);
    expect(notify).not.toHaveBeenCalled();
    await Promise.resolve();
    expect(store.getSnapshot()).toBe(initial + 2);
    expect(notify).toHaveBeenCalledTimes(1);
    expect(store.subscribe).toBe(subscribe);

    unsubscribe();
    store.dispose();
    store.dispose();
    hub.send(PropertyChangedMessage.create({}, "test", "value"));
    expect(store.getSnapshot()).toBe(initial + 2);
  });

  it("disconnects, reconnects, and treats repeated cleanup or post-dispose subscribe as safe", async () => {
    const hub = new MessageHub();
    const store = createVmxStore(hub);
    const first = store.subscribe(() => {});
    first();
    first();
    hub.send(PropertyChangedMessage.create({}, "test", "missed"));
    await Promise.resolve();
    expect(store.getSnapshot()).toBe(1);

    const notify = vi.fn();
    const second = store.subscribe(notify);
    expect(store.getSnapshot()).toBe(2);
    hub.send(PropertyChangedMessage.create({}, "test", "observed"));
    await Promise.resolve();
    expect(notify).toHaveBeenCalledTimes(1);
    second();
    store.dispose();
    store.subscribe(() => {})();
  });

  it("catches a VM mutation between render and subscription installation", () => {
    const hub = new MessageHub();
    const vm = modeled(hub);
    const store = createVmxStore(hub);
    function Probe(): JSX.Element {
      return <span data-testid="commit-gap">{useVmx(store, () => vm.model)}</span>;
    }
    function InterleavedMutation(): null {
      useInsertionEffect(() => { vm.model = 1; }, []);
      return null;
    }
    render(<><Probe /><InterleavedMutation /></>);
    expect(screen.getByTestId("commit-gap").textContent).toBe("1");
  });

  it("shares one hub subscription and tears it down across StrictMode mounts", () => {
    const messages = new Subject<IMessage>();
    let subscriptions = 0;
    const hub: IMessageHub = {
      messages: new Observable((subscriber) => {
        subscriptions += 1;
        const inner = messages.subscribe(subscriber);
        return () => {
          subscriptions -= 1;
          inner.unsubscribe();
        };
      }),
      send: (message) => messages.next(message),
    };
    const store = createVmxStore(hub);
    function Probe(): JSX.Element {
      useVmx(store, () => "stable");
      return <span>ready</span>;
    }

    const mounted = render(<StrictMode><Probe /><Probe /></StrictMode>);
    expect(subscriptions).toBe(1);
    mounted.unmount();
    expect(subscriptions).toBe(0);
  });

  it("suppresses unrelated renders and coalesces a hub batch to final selector state", async () => {
    const hub = new MessageHub();
    const vm = modeled(hub);
    const store = createVmxStore(hub);
    const renders = vi.fn();
    function Probe(): JSX.Element {
      const value = useVmx(store, () => vm.model);
      renders(value);
      return <span data-testid="selected">{value}</span>;
    }
    render(<Probe />);
    await act(async () => {
      hub.send(PropertyChangedMessage.create({}, "other", "value"));
      await Promise.resolve();
    });
    expect(renders).toHaveBeenCalledTimes(1);

    await act(async () => {
      hub.batch(() => {
        vm.model = 1;
        vm.model = 2;
      });
      await Promise.resolve();
    });
    expect(screen.getByTestId("selected").textContent).toBe("2");
    expect(renders).toHaveBeenCalledTimes(2);
  });

  it("uses stable server snapshots without subscribing during SSR", () => {
    const messages = new Subject<IMessage>();
    let subscriptions = 0;
    const hub: IMessageHub = {
      messages: new Observable((subscriber) => {
        subscriptions += 1;
        const inner = messages.subscribe(subscriber);
        return () => {
          subscriptions -= 1;
          inner.unsubscribe();
        };
      }),
      send: (message) => messages.next(message),
    };
    const store = createVmxStore(hub);
    function Probe(): JSX.Element {
      return <span>{useVmx(store, () => "server")}</span>;
    }
    expect(renderToString(<Probe />)).toContain("server");
    expect(subscriptions).toBe(0);
  });

  it("selects FormVM state through the shared hub store", async () => {
    const hub = new MessageHub();
    const form = new FormVM({ initial: { title: "draft" }, persister: async () => {}, hub });
    const store = createVmxStore(hub);
    function Probe(): JSX.Element {
      return <span>{useVmx(store, () => form.model.title)}</span>;
    }
    const mounted = render(<Probe />);
    await act(async () => {
      form.setModel({ title: "ready" });
      await Promise.resolve();
    });
    expect(mounted.container.textContent).toBe("ready");
  });

  it("hydrates the same server snapshot without a mismatch", async () => {
    const store = createVmxStore(new MessageHub());
    function Probe(): JSX.Element {
      return <span>{useVmx(store, () => "hydrated")}</span>;
    }
    const container = document.createElement("div");
    container.innerHTML = renderToString(<Probe />);
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    let root: ReturnType<typeof hydrateRoot> | undefined;
    await act(async () => {
      root = hydrateRoot(container, <Probe />);
      await Promise.resolve();
    });
    expect(container.textContent).toBe("hydrated");
    expect(error).not.toHaveBeenCalled();
    await act(async () => root?.unmount());
    error.mockRestore();
  });
});

describe("VM and value hooks", () => {
  it("re-renders useVm only for its sender and supports selector equality", async () => {
    const hub = new MessageHub();
    const vm = modeled(hub);
    const other = modeled(hub, 10);
    const wholeRenders = vi.fn();
    const selectorRenders = vi.fn();
    function WholeProbe(): JSX.Element {
      const live = useVm(vm);
      wholeRenders(live.model);
      return <span>{live.model}</span>;
    }
    function SelectorProbe(): JSX.Element {
      const parity = useVm(vm, (source) => source.model % 2);
      selectorRenders(parity);
      return <span>{parity}</span>;
    }
    render(<><WholeProbe /><SelectorProbe /></>);
    const wholeBaseline = wholeRenders.mock.calls.length;
    const selectorBaseline = selectorRenders.mock.calls.length;
    await act(async () => { other.model = 11; await Promise.resolve(); });
    expect(wholeRenders).toHaveBeenCalledTimes(wholeBaseline);
    await act(async () => { vm.model = 2; await Promise.resolve(); });
    expect(wholeRenders).toHaveBeenCalledTimes(wholeBaseline + 1);
    expect(selectorRenders).toHaveBeenCalledTimes(selectorBaseline);
    await act(async () => { vm.model = 3; await Promise.resolve(); });
    expect(selectorRenders).toHaveBeenCalledTimes(selectorBaseline + 1);
  });

  it("catches a focused VM mutation between render and subscription installation", () => {
    const vm = modeled(new MessageHub());
    function Probe(): JSX.Element {
      return <span data-testid="vm-gap">{useVm(vm).model}</span>;
    }
    function InterleavedMutation(): null {
      useInsertionEffect(() => { vm.model = 1; }, []);
      return null;
    }
    render(<><Probe /><InterleavedMutation /></>);
    expect(screen.getByTestId("vm-gap").textContent).toBe("1");
  });

  it("supports the rules-of-hooks-safe conditional child pattern", () => {
    const hub = new MessageHub();
    const vm = modeled(hub);
    function Bound({ value }: { value: ComponentVMOf<number> }): JSX.Element {
      return <span data-testid="conditional">{useVm(value).model}</span>;
    }
    function Parent({ value }: { value: ComponentVMOf<number> | null }): JSX.Element {
      return value === null ? <span>empty</span> : <Bound value={value} />;
    }
    const mounted = render(<Parent value={null} />);
    mounted.rerender(<Parent value={vm} />);
    expect(screen.getByTestId("conditional").textContent).toBe("0");
    mounted.rerender(<Parent value={null} />);
    expect(screen.queryByTestId("conditional")).toBeNull();
  });

  it("observes DerivedProperty and AsyncResourceVM without polling", async () => {
    const source = new BehaviorSubject(1);
    const derived = new DerivedProperty(source);
    const resource = new AsyncResourceVM({
      name: "resource",
      loader: async () => "loaded",
      hub: new MessageHub(),
      dispatcher: NullDispatcher.INSTANCE,
    });
    function Probe(): JSX.Element {
      const value = useDerivedProperty(derived);
      const state = useAsyncResource(resource);
      return <span data-testid="resource">{value}:{state.status}</span>;
    }
    render(<Probe />);
    await act(async () => { source.next(2); await Promise.resolve(); });
    expect(screen.getByTestId("resource").textContent).toBe("2:Idle");
    await act(async () => { await resource.load(); await Promise.resolve(); });
    expect(screen.getByTestId("resource").textContent).toBe(`2:${AsyncResourceStatus.Ready}`);
  });

  it("returns undefined for an unseeded DerivedProperty", () => {
    const property = new DerivedProperty<number>(new Observable(() => {}));
    function Probe(): JSX.Element {
      return <span>{String(useDerivedProperty(property))}</span>;
    }
    expect(render(<Probe />).container.textContent).toBe("undefined");
  });
});

describe("command and collection hooks", () => {
  it("tracks command state and returns a stable execute callback", () => {
    let allowed = false;
    const task = vi.fn();
    const command = RelayCommand.builder().predicate(() => allowed).task(task).build();
    const renders = vi.fn();
    let firstExecute: (() => void) | undefined;
    let latestExecute: (() => void) | undefined;
    function Probe(): JSX.Element {
      const binding = useCommand(command);
      firstExecute ??= binding.execute;
      latestExecute = binding.execute;
      renders(binding.canExecute);
      return <button disabled={!binding.canExecute} onClick={binding.execute}>run</button>;
    }
    render(<Probe />);
    allowed = true;
    act(() => command.raiseCanExecuteChanged());
    const button = screen.getByRole("button");
    expect((button as HTMLButtonElement).disabled).toBe(false);
    expect(firstExecute).toBe(latestExecute);
    act(() => button.click());
    expect(task).toHaveBeenCalledTimes(1);
    expect(renders).toHaveBeenCalledTimes(2);
  });

  it("keeps ObservableList snapshots stable and emits one render for a batch", () => {
    const list = new ObservableList<number>();
    const snapshots: number[][] = [];
    function Probe(): JSX.Element {
      const items = useObservableList(list);
      snapshots.push([...items]);
      return <span data-testid="list">{items.join(",")}</span>;
    }
    render(<Probe />);
    act(() => list.withBatch(() => { list.push(1); list.push(2); }));
    expect(screen.getByTestId("list").textContent).toBe("1,2");
    expect(snapshots).toHaveLength(2);
  });

  it("publishes same-length replacements while preserving unaffected identity", () => {
    const first = { id: "first" };
    const second = { id: "second" };
    const replacement = { id: "replacement" };
    const list = new ObservableList<{ readonly id: string }>();
    list.withBatch(() => { list.push(first); list.push(second); });
    const renders = vi.fn();
    let latest: readonly { readonly id: string }[] = [];
    function Probe(): JSX.Element {
      latest = useObservableList(list);
      renders(latest);
      return <span>{latest.map((item) => item.id).join(",")}</span>;
    }
    render(<Probe />);
    const initial = latest;
    act(() => list.replace(1, replacement));
    expect(latest).not.toBe(initial);
    expect(latest[0]).toBe(first);
    expect(latest[1]).toBe(replacement);
    expect(renders).toHaveBeenCalledTimes(2);
  });

  it("catches a list mutation between render and subscription installation", () => {
    const list = new ObservableList<number>();
    function Probe(): JSX.Element {
      return <span data-testid="list-gap">{useObservableList(list).join(",")}</span>;
    }
    function InterleavedMutation(): null {
      useInsertionEffect(() => { list.push(1); }, []);
      return null;
    }
    render(<><Probe /><InterleavedMutation /></>);
    expect(screen.getByTestId("list-gap").textContent).toBe("1");
  });

  it("preserves VM identity and order across collection moves", () => {
    const hub = new MessageHub();
    const first = ComponentVM.create({ name: "first", hub, dispatcher: NullDispatcher.INSTANCE });
    const second = ComponentVM.create({ name: "second", hub, dispatcher: NullDispatcher.INSTANCE });
    const collection = CompositeVM.create<ComponentVM>({
      name: "items",
      hub,
      dispatcher: NullDispatcher.INSTANCE,
      children: () => [first, second],
    });
    collection.construct();
    let latest: readonly ComponentVM[] = [];
    function Probe(): JSX.Element {
      latest = useVmCollection(collection);
      return <span data-testid="vms">{latest.map((item) => item.name).join(",")}</span>;
    }
    render(<Probe />);
    act(() => collection.move(0, 1));
    expect(screen.getByTestId("vms").textContent).toBe("second,first");
    expect(latest[0]).toBe(second);
    expect(latest[1]).toBe(first);
  });

  it("catches a VM collection mutation between render and subscription installation", () => {
    const hub = new MessageHub();
    const first = ComponentVM.create({ name: "first", hub, dispatcher: NullDispatcher.INSTANCE });
    const collection = CompositeVM.create<ComponentVM>({
      name: "items",
      hub,
      dispatcher: NullDispatcher.INSTANCE,
      children: () => [],
    });
    collection.construct();
    function Probe(): JSX.Element {
      return <span data-testid="collection-gap">{useVmCollection(collection).length}</span>;
    }
    function InterleavedMutation(): null {
      useInsertionEffect(() => { collection.add(first); }, []);
      return null;
    }
    render(<><Probe /><InterleavedMutation /></>);
    expect(screen.getByTestId("collection-gap").textContent).toBe("1");
  });
});

describe("shallowEqual", () => {
  it("uses Object.is and one-level array/object comparison", () => {
    expect(shallowEqual(Number.NaN, Number.NaN)).toBe(true);
    expect(shallowEqual([1, "a"], [1, "a"])).toBe(true);
    expect(shallowEqual(1, 2)).toBe(false);
    expect(shallowEqual([1], [2])).toBe(false);
    expect(shallowEqual([1], [1, 2])).toBe(false);
    expect(shallowEqual({ a: 1 }, { a: 1 })).toBe(true);
    expect(shallowEqual({ a: 1 }, { a: 2 })).toBe(false);
    expect(shallowEqual({ a: 1 }, { b: 1 })).toBe(false);
    expect(shallowEqual([1], { 0: 1 })).toBe(false);
  });
});
