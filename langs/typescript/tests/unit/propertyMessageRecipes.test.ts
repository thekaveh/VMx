/**
 * Executable form of the property and message recipes in
 * docs/content/primitives/state-reactive-helpers.md,
 * docs/content/primitives/services-messages-dispatching.md and
 * docs/content/flavors/typescript.md §7.4.7. The docs-snippet regions are
 * shown there verbatim, dedented, and `make docs-check` keeps them equal. No
 * conformance ID (recipes; #659).
 */
import { BehaviorSubject, filter, startWith, Subject, type Observable } from "rxjs";
import { describe, expect, it } from "vitest";
import {
  ComponentVMBase,
  ComponentVMOf,
  fromTwo,
  isPropertyChanged,
  MessageHub,
  RxDispatcher,
  subscribeValue,
  ViewModelType,
  whenPropertyChanged,
  type DerivedProperty,
  type IDispatcher,
  type IMessage,
  type IMessageHub,
} from "../../src/index.js";
import { createTestServices, recordPropertyChanges } from "../../src/testing/index.js";

const makeServices = () => ({ hub: new MessageHub(), dispatcher: RxDispatcher.immediate() });

// docs-snippet:start derived-total
class CartVM extends ComponentVMBase {
  readonly #quantity$ = new BehaviorSubject(1);
  readonly #total: DerivedProperty<number>;

  constructor(prices: Observable<number>, hub: IMessageHub, dispatcher: IDispatcher) {
    super({ name: "cart", hub, dispatcher });
    // Seed every source, so `total` has a value at once (DPROP-001).
    this.#total = this.own(
      fromTwo(prices.pipe(startWith(0)), this.#quantity$, (price, quantity) => price * quantity),
    );
    // A DerivedProperty sends nothing on the hub. Forward each change.
    this.own(this.#total.valueChanged.subscribe(() => this._notifyPropertyChanged("total")));
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get total(): number {
    return this.#total.value;
  }

  get quantity(): number {
    return this.#quantity$.value;
  }

  // No compare-and-assign helper: compare, assign, then notify.
  set quantity(value: number) {
    if (this.#quantity$.value === value) return;
    this.#quantity$.next(value);
    this._notifyPropertyChanged("quantity");
  }
}
// docs-snippet:end derived-total

class EditorVM extends ComponentVMBase {
  #title = "Untitled";
  #dirty = false;

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get title(): string {
    return this.#title;
  }

  set title(value: string) {
    if (this.#title === value) return;
    this.#title = value;
    this._notifyPropertyChanged("title");
  }

  get dirty(): boolean {
    return this.#dirty;
  }

  set dirty(value: boolean) {
    if (this.#dirty === value) return;
    this.#dirty = value;
    this._notifyPropertyChanged("dirty");
  }

  // A third property that the header does not watch.
  get hint(): string {
    return "";
  }

  touchHint(): void {
    this._notifyPropertyChanged("hint");
  }
}

// docs-snippet:start watch-properties
class HeaderVM extends ComponentVMBase {
  readonly #editor: EditorVM;

  constructor(editor: EditorVM, hub: IMessageHub, dispatcher: IDispatcher) {
    super({ name: "header", hub, dispatcher });
    this.#editor = editor;
    // One owned subscription per watched property of the source.
    for (const name of ["title", "dirty"]) {
      this.own(
        whenPropertyChanged(editor.hub, editor, name).subscribe(() =>
          this._notifyPropertyChanged("label"),
        ),
      );
    }
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get label(): string {
    return this.#editor.dirty ? `${this.#editor.title} *` : this.#editor.title;
  }
}
// docs-snippet:end watch-properties

interface Note {
  title: string;
}

interface Plot {
  readonly points: readonly number[];
}

class ChartVM extends ComponentVMBase {
  #plot: Plot = { points: [] };

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get plot(): Plot {
    return this.#plot;
  }

  set plot(value: Plot) {
    if (this.#plot === value) return;
    this.#plot = value;
    this._notifyPropertyChanged("plot");
  }
}

class PanelVM extends ComponentVMBase {
  readonly chart: ChartVM;

  constructor(hub: IMessageHub, dispatcher: IDispatcher) {
    super({ name: "panel", hub, dispatcher });
    this.chart = this.own(new ChartVM({ name: "chart", hub, dispatcher }));
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }
}

// docs-snippet:start request-message
// An application message: the hub carries any IMessage.
class NavigateRequest implements IMessage {
  constructor(
    readonly sender: unknown,
    readonly senderName: string,
    readonly route: string,
  ) {}
}
// docs-snippet:end request-message

describe("derived value recipe", () => {
  it("is readable at once, stays silent at first, and publishes each change", () => {
    const { hub, dispatcher } = makeServices();
    const changes = recordPropertyChanges(hub);
    const prices = new Subject<number>();
    const cart = new CartVM(prices, hub, dispatcher);

    // DPROP-001: the seeded sources give a value at construction.
    expect(cart.total).toBe(0);
    // DPROP-009: the first value is not a change, so nothing is published.
    expect(changes.propertyNames).toEqual([]);

    prices.next(10);
    expect(cart.total).toBe(10);
    expect(changes.propertyNames).toEqual(["total"]);

    changes.clear();
    cart.quantity = 3;
    expect(cart.total).toBe(30);
    expect(changes.propertyNames).toEqual(["total", "quantity"]);
    expect(changes.records.every((record) => record.sender === cart)).toBe(true);

    // The setter compares first: the same value publishes nothing.
    changes.clear();
    cart.quantity = 3;
    expect(changes.propertyNames).toEqual([]);

    // Disposal releases the owned derived property and its forwarding.
    cart.dispose();
    prices.next(20);
    expect(changes.propertyNames).toEqual([]);
    changes.dispose();
  });
});

describe("several properties of one source", () => {
  it("refreshes for each watched name and ignores the others", () => {
    const { hub, dispatcher } = makeServices();
    const editor = new EditorVM({ name: "editor", hub, dispatcher });
    const header = new HeaderVM(editor, hub, dispatcher);
    const labels = recordPropertyChanges(hub, { sender: header, propertyName: "label" });

    editor.title = "Draft";
    editor.dirty = true;
    editor.touchHint();
    expect(labels.records).toHaveLength(2);
    expect(header.label).toBe("Draft *");

    header.dispose();
    editor.title = "Final";
    expect(labels.records).toHaveLength(2);
    labels.dispose();
  });

  it("can use one predicate subscription in TypeScript", () => {
    const { hub, dispatcher } = makeServices();
    const editor = new EditorVM({ name: "editor", hub, dispatcher });
    let refreshes = 0;
    const refreshHeader = (): void => {
      refreshes += 1;
    };

    // docs-snippet:start watch-properties-predicate
    const watched = new Set(["title", "dirty"]);
    const subscription = editor.hub.messages
      .pipe(filter((m) => isPropertyChanged(m, { sender: editor }) && watched.has(m.propertyName)))
      .subscribe(() => refreshHeader());
    // docs-snippet:end watch-properties-predicate

    editor.title = "Draft";
    editor.dirty = true;
    editor.touchHint();
    expect(refreshes).toBe(2);
    subscription.unsubscribe();
  });
});

describe("same-value republish recipe", () => {
  it("fires on a same-reference republish only with an always-false equality", () => {
    const { hub, dispatcher } = makeServices();
    const note = new ComponentVMOf<Note>({
      name: "note",
      initialModel: { title: "Draft" },
      hub,
      dispatcher,
    });
    const defaultRenders: Note[] = [];
    const defaultSubscription = subscribeValue(
      note,
      (vm) => vm.model,
      (model) => defaultRenders.push(model),
    );

    // docs-snippet:start republish
    const renders: Note[] = [];
    const subscription = subscribeValue(
      note,
      (vm) => vm.model,
      (model) => renders.push(model),
      // Never equal: each property message from `note` calls the callback.
      { equality: () => false },
    );

    note.model.title = "Edited in place";
    note.republishModel(); // same reference as before
    // docs-snippet:end republish

    expect(renders).toEqual([note.model]);
    expect(renders[0]).toBe(note.model);
    // The default Object.is equality hides the same-reference republish.
    expect(defaultRenders).toEqual([]);

    subscription.unsubscribe();
    defaultSubscription.unsubscribe();
  });
});

describe("nested value recipe", () => {
  it("binds the child directly, and the parent publishes nothing", () => {
    const { hub, dispatcher } = makeServices();
    const panel = new PanelVM(hub, dispatcher);
    const fromPanel = recordPropertyChanges(hub, { sender: panel });
    const drawn: Plot[] = [];
    const draw = (plot: Plot): void => {
      drawn.push(plot);
    };

    // docs-snippet:start nested-child
    // The child sends its own PropertyChangedMessage. Bind to it directly.
    const subscription = subscribeValue(panel.chart, (chart) => chart.plot, draw);
    // docs-snippet:end nested-child

    const next = { points: [1, 2, 3] };
    panel.chart.plot = next;
    expect(drawn).toEqual([next]);
    expect(fromPanel.records).toEqual([]);

    subscription.unsubscribe();
    fromPanel.dispose();
  });
});

describe("request message recipe", () => {
  it("loses a request sent before the host subscribes and delivers to every subscriber", () => {
    const { hub } = makeServices();
    const toolbar = { name: "toolbar" };
    const routes: string[] = [];
    const router = {
      navigate: (route: string): void => {
        routes.push(route);
      },
    };

    // The hub is hot and does not replay: nobody listens yet.
    hub.send(new NavigateRequest(toolbar, toolbar.name, "/lost"));

    // docs-snippet:start request-host
    // Subscribe the host before any view-model can send a request.
    const host = hub.messages
      .pipe(filter((m): m is NavigateRequest => m instanceof NavigateRequest))
      .subscribe((request) => router.navigate(request.route));

    hub.send(new NavigateRequest(toolbar, toolbar.name, "/settings"));
    // docs-snippet:end request-host

    expect(routes).toEqual(["/settings"]);

    // Every subscriber receives each request; the hub picks no handler.
    const audit: string[] = [];
    const auditor = hub.messages
      .pipe(filter((m): m is NavigateRequest => m instanceof NavigateRequest))
      .subscribe((request) => audit.push(request.route));
    hub.send(new NavigateRequest(toolbar, toolbar.name, "/help"));
    expect(routes).toEqual(["/settings", "/help"]);
    expect(audit).toEqual(["/help"]);

    host.unsubscribe();
    auditor.unsubscribe();
  });
});

describe("recording every sender recipe", () => {
  it("records both senders on a shared hub without a sender filter", () => {
    // docs-snippet:start record-every-sender
    const services = createTestServices();
    const first = new ComponentVMOf({
      name: "first",
      initialModel: 1,
      hub: services.hub,
      dispatcher: services.dispatcher,
    });
    const second = new ComponentVMOf({
      name: "second",
      initialModel: 1,
      hub: services.hub,
      dispatcher: services.dispatcher,
    });
    // No sender filter: the recorder keeps every sender on the hub.
    const changes = recordPropertyChanges(services.hub);

    first.model = 2;
    second.model = 2;

    expect(changes.records.map((record) => record.sender)).toEqual([first, second]);
    expect(changes.propertyNames).toEqual(["model", "model"]);
    changes.dispose();
    services.dispose();
    // docs-snippet:end record-every-sender
  });
});
