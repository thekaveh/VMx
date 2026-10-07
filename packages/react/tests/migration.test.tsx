// Before/after fixtures for docs/content/getting-started/upgrading-typescript.md.
// Each "before" shape is what a consumer written against an older VMx line
// contains; a shape that no longer compiles is pinned with @ts-expect-error so
// the guide's claim fails loudly if the core changes again.
import { type JSX } from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { Observable, Subject } from "rxjs";
import { afterEach, describe, expect, it } from "vitest";
import {
  ComponentVMOf,
  MessageHub,
  NullDispatcher,
  ObservableList,
  type IMessage,
  type IMessageHub,
} from "@thekaveh/vmx";

import {
  createVmxStore,
  shallowEqual,
  useObservableList,
  useVm,
  useVmx,
  type VmxStore,
} from "../src/index.js";

afterEach(cleanup);

interface Run {
  readonly name: string;
  readonly status: string;
  readonly notes: string;
}

function runOptions(hub: IMessageHub, model: Run) {
  return {
    name: "run",
    hint: "",
    initialModel: model,
    modeledHinter: (run: Run) => run.name,
    hub,
    dispatcher: NullDispatcher.INSTANCE,
  };
}

// Recipe 1, before: a consumer class from core < 3.10 that stored and exposed
// its own hub. Core 3.10 added the read-only `hub` accessor, so the redundant
// field no longer compiles (TS2610).
// docs-snippet:start upgrade-hub-before
class LegacyRunVM extends ComponentVMOf<Run> {
  // docs-snippet:end upgrade-hub-before
  // @ts-expect-error -- core owns `hub` as an accessor since 3.10.0
  // docs-snippet:start upgrade-hub-before
  readonly hub: IMessageHub;

  constructor(hub: IMessageHub, model: Run) {
    super(runOptions(hub, model));
    this.hub = hub;
  }
}
// docs-snippet:end upgrade-hub-before

// Recipe 1, after: delete the redundant member and use the inherited `hub`.
// docs-snippet:start upgrade-hub-after
class RunVM extends ComponentVMOf<Run> {
  constructor(hub: IMessageHub, model: Run) {
    super(runOptions(hub, model));
  }
  // docs-snippet:end upgrade-hub-after

  rename(name: string): void {
    this.model = { ...this.model, name };
  }

  annotate(notes: string): void {
    this.model = { ...this.model, notes };
  }
  // docs-snippet:start upgrade-hub-after
}
// docs-snippet:end upgrade-hub-after

// Recipe 2, before: a consumer-local property-list hook. It re-renders on every
// property change of the VM and copies the listed values (consumer-local; not
// part of VMx).
// docs-snippet:start upgrade-selector-before
function useRunFields(vm: RunVM): Pick<Run, "name" | "status"> {
  useVm(vm);
  const { name, status } = vm.model;
  return { name, status };
}
// docs-snippet:end upgrade-selector-before

// Recipe 3, after: a consumer-local hub-first wrapper that shares one store per
// hub (consumer-local; VMx ships createVmxStore, not this cache).
// docs-snippet:start upgrade-hub-first-store
const storesByHub = new WeakMap<IMessageHub, VmxStore>();
function storeForHub(hub: IMessageHub): VmxStore {
  let store = storesByHub.get(hub);
  if (store === undefined) {
    store = createVmxStore(hub);
    storesByHub.set(hub, store);
  }
  return store;
}
// docs-snippet:end upgrade-hub-first-store

function countingHub(): { hub: IMessageHub; subscriptions: () => number } {
  const messages = new Subject<IMessage>();
  let subscriptions = 0;
  return {
    hub: {
      messages: new Observable<IMessage>((subscriber) => {
        subscriptions += 1;
        const inner = messages.subscribe(subscriber);
        return () => {
          subscriptions -= 1;
          inner.unsubscribe();
        };
      }),
      send: (message) => messages.next(message),
    },
    subscriptions: () => subscriptions,
  };
}

const run: Run = { name: "baseline", status: "queued", notes: "" };

describe("upgrade recipe: inherited hub accessor", () => {
  it("exposes the injected hub without a consumer member", () => {
    const hub = new MessageHub();
    const vm = new RunVM(hub, run);

    expect(vm.hub).toBe(hub);
    expect(LegacyRunVM.name).toBe("LegacyRunVM");
  });
});

describe("upgrade recipe: selector projections", () => {
  it("re-renders a projection only when a selected field changes", () => {
    const vm = new RunVM(new MessageHub(), run);
    const renders = { before: 0, after: 0 };
    function Before(): JSX.Element {
      renders.before += 1;
      const fields = useRunFields(vm);
      return <span>{`before:${fields.name}:${fields.status}`}</span>;
    }
    function After(): JSX.Element {
      renders.after += 1;
      // docs-snippet:start upgrade-selector-after
      const fields = useVm(
        vm,
        (current) => ({ name: current.model.name, status: current.model.status }),
        shallowEqual,
      );
      // docs-snippet:end upgrade-selector-after
      return <span>{`after:${fields.name}:${fields.status}`}</span>;
    }
    render(<><Before /><After /></>);
    const initial = { ...renders };

    act(() => vm.annotate("unrelated"));
    expect(renders.before).toBe(initial.before + 1);
    expect(renders.after).toBe(initial.after);

    act(() => vm.rename("renamed"));
    expect(screen.getByText("before:renamed:queued")).toBeTruthy();
    expect(screen.getByText("after:renamed:queued")).toBeTruthy();
    expect(renders.after).toBe(initial.after + 1);
  });
});

describe("upgrade recipe: read-only list snapshots", () => {
  it("sorts a copy and refreshes when the list changes", () => {
    const list = new ObservableList<number>();
    list.push(3);
    list.push(1);
    function Sorted(): JSX.Element {
      // docs-snippet:start upgrade-list-after
      const items = useObservableList(list);
      const sorted = [...items].sort((left, right) => left - right);
      // docs-snippet:end upgrade-list-after
      // Before: the snapshot was a mutable array sorted in place.
      // @ts-expect-error -- the adapter returns readonly T[]
      void (() => items.sort());
      return <span>{sorted.join(",")}</span>;
    }
    render(<Sorted />);
    expect(screen.getByText("1,3")).toBeTruthy();

    act(() => list.push(2));

    expect(screen.getByText("1,2,3")).toBeTruthy();
    expect(list.toArray()).toEqual([3, 1, 2]);
  });
});

describe("upgrade recipe: hub-first store lifetime", () => {
  it("shares one hub subscription per hub and releases it on unmount", () => {
    const { hub, subscriptions } = countingHub();
    function Status({ label }: { label: string }): JSX.Element {
      useVmx(storeForHub(hub), () => label);
      return <span>{label}</span>;
    }

    const mounted = render(<><Status label="one" /><Status label="two" /></>);
    expect(subscriptions()).toBe(1);

    mounted.unmount();
    expect(subscriptions()).toBe(0);
  });

  it("releases a focused useVm subscription on unmount", () => {
    const { hub, subscriptions } = countingHub();
    const vm = new RunVM(hub, run);
    function Name(): JSX.Element {
      const name = useVm(vm, (current) => current.model.name);
      return <span>{name}</span>;
    }

    const mounted = render(<Name />);
    expect(subscriptions()).toBe(1);

    mounted.unmount();
    expect(subscriptions()).toBe(0);
  });
});
