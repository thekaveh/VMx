/**
 * Executable form of the authoring recipes in
 * docs/content/primitives/viewmodel-families/component-family.md and the
 * owned-child order in docs/content/primitives/disposal-contract.md. The
 * docs-snippet regions are shown there verbatim, dedented, and
 * `make docs-check` keeps them equal. No conformance ID (recipes; #658).
 */
import { Subject, type Subscription } from "rxjs";
import { describe, expect, it } from "vitest";
import {
  AsyncResourceStatus,
  AsyncResourceVM,
  ComponentVMBase,
  ConstructionStatus,
  ConstructionStatusChangedMessage,
  MessageHub,
  RelayCommand,
  RxDispatcher,
  ViewModelType,
  type IDispatcher,
  type IMessageHub,
} from "../../src/index.js";

interface Metric {
  value: number;
}

interface MetricApi {
  fetch(signal: AbortSignal): Promise<Metric[]>;
  readonly ticks: Subject<number>;
}

// docs-snippet:start component-authoring
class MetricVM extends ComponentVMBase {
  readonly #api: MetricApi;
  readonly resource: AsyncResourceVM<Metric[]>;
  readonly refreshCommand: RelayCommand;
  #tickSubscription: Subscription | null = null;

  constructor(api: MetricApi, hub: IMessageHub, dispatcher: IDispatcher) {
    super({ name: "metric", hub, dispatcher });
    this.#api = api;
    // The loader runs after construction, so it can read #private state.
    this.resource = this.own(
      new AsyncResourceVM({
        name: "metric-data",
        hub,
        dispatcher,
        loader: (signal) => this.#api.fetch(signal),
      }),
    );
    // Owned: disposing MetricVM disposes the command, which is then inert.
    this.refreshCommand = this.own(
      RelayCommand.builder()
        .task(() => void this.resource.load())
        .build(),
    );
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  // A per-construct subscription starts on construct and ends on destruct.
  protected override _onConstruct(): void {
    super._onConstruct();
    this.#tickSubscription = this.#api.ticks.subscribe(() => {
      void this.resource.load();
    });
  }

  protected override _onDestruct(): void {
    this.#tickSubscription?.unsubscribe();
    this.#tickSubscription = null;
    super._onDestruct();
  }
}
// docs-snippet:end component-authoring

function api(): MetricApi & { calls: number } {
  const ticks = new Subject<number>();
  const fake = {
    calls: 0,
    ticks,
    fetch: (_signal: AbortSignal): Promise<Metric[]> => {
      fake.calls += 1;
      return Promise.resolve([{ value: fake.calls }]);
    },
  };
  return fake;
}

const services = () => ({ hub: new MessageHub(), dispatcher: RxDispatcher.immediate() });

describe("component authoring recipes", () => {
  it("lets the loader read #private state after construction", async () => {
    const fake = api();
    const { hub, dispatcher } = services();
    const vm = new MetricVM(fake, hub, dispatcher);

    await vm.resource.load();

    expect(fake.calls).toBe(1);
    expect(vm.resource.state.status).toBe(AsyncResourceStatus.Ready);
  });

  it("subscribes per construct and releases on destruct", () => {
    const fake = api();
    const { hub, dispatcher } = services();
    const vm = new MetricVM(fake, hub, dispatcher);

    vm.construct();
    expect(fake.ticks.observed).toBe(true);
    vm.destruct();
    expect(fake.ticks.observed).toBe(false);
    vm.construct();
    expect(fake.ticks.observed).toBe(true);
    vm.dispose();
  });

  it("makes an owned command inert at disposal, while an unowned one stays live", () => {
    const fake = api();
    const { hub, dispatcher } = services();
    const vm = new MetricVM(fake, hub, dispatcher);
    let unownedRuns = 0;
    const unowned = RelayCommand.builder()
      .task(() => (unownedRuns += 1))
      .build();

    vm.dispose();
    vm.refreshCommand.execute();
    unowned.execute();

    expect(vm.refreshCommand.canExecute()).toBe(false);
    expect(fake.calls).toBe(0);
    expect(unownedRuns).toBe(1);
  });

  it("keeps an external trigger subscribed until the command itself is disposed", () => {
    const { hub, dispatcher } = services();
    class HolderVM extends ComponentVMBase {
      readonly command: RelayCommand;

      constructor(trigger: Subject<void>) {
        super({ name: "holder", hub, dispatcher });
        this.command = this.own(
          RelayCommand.builder()
            .task(() => undefined)
            .triggers(trigger)
            .build(),
        );
      }

      get type(): ViewModelType {
        return ViewModelType.Component;
      }
    }
    const ownedTrigger = new Subject<void>();
    const unownedTrigger = new Subject<void>();
    const holder = new HolderVM(ownedTrigger);
    const unowned = RelayCommand.builder()
      .task(() => undefined)
      .triggers(unownedTrigger)
      .triggers(holder.propertyChanged)
      .build();
    let ownerStreamCompleted = false;
    holder.propertyChanged.subscribe({ complete: () => (ownerStreamCompleted = true) });

    holder.dispose();

    expect(ownedTrigger.observed).toBe(false);
    // The owner's propertyChanged completes, so a trigger on it is released,
    expect(ownerStreamCompleted).toBe(true);
    // but the unowned command still holds its external subscription.
    expect(unownedTrigger.observed).toBe(true);
    unowned.dispose();
    expect(unownedTrigger.observed).toBe(false);
  });

  it("disposes an owned child after the parent publishes Disposed", () => {
    const { hub, dispatcher } = services();
    const order: string[] = [];
    hub.messages.subscribe((message) => {
      if (
        message instanceof ConstructionStatusChangedMessage &&
        message.status === ConstructionStatus.Disposed
      ) {
        order.push((message.sender as MetricVM | AsyncResourceVM<Metric[]>).name);
      }
    });
    const vm = new MetricVM(api(), hub, dispatcher);

    vm.dispose();

    expect(order).toEqual(["metric", "metric-data"]);
  });

  it("reserves base member names such as status", () => {
    class PanelVM extends ComponentVMBase {
      // @ts-expect-error -- `status` is a base accessor; name a derived status differently.
      status = "loading";

      get type(): ViewModelType {
        return ViewModelType.Component;
      }
    }

    expect(PanelVM).toBeDefined();
  });
});
