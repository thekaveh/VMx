/**
 * NotificationsVM — subscribes to an INotificationHub and surfaces the most
 * recent notifications as a bounded list of NotificationVM (cap = 5).
 *
 * VMx-API adaptation: VMx's `NotificationVM` requires a `SchedulerLike`
 * (RxJS) and a lifespan; passing `asyncScheduler` + a configurable lifespan
 * lets tests inject `VirtualTimeScheduler` for deterministic timer control
 * (per the cross-language note re Python's TimeoutScheduler / TestScheduler).
 */
import { asyncScheduler, type SchedulerLike } from "rxjs";
import {
  ComponentVMBase,
  PropertyChangedMessage,
  ViewModelType,
  type IDispatcher,
  type IMessageHub,
} from "vmx";
import {
  type INotificationHub,
  type Notification,
  NotificationVM,
} from "vmx/notifications";

export class NotificationsVM extends ComponentVMBase {
  static readonly DEFAULT_CAP = 5;

  readonly #notificationHub: INotificationHub;
  readonly #scheduler: SchedulerLike;
  readonly #lifespanMs: number | undefined;
  readonly #cap: number;
  readonly #visible: NotificationVM[] = [];
  readonly #map = new Map<Notification, NotificationVM>();
  #pendingSub: { unsubscribe(): void } | null = null;

  constructor(opts: {
    name: string;
    hint: string;
    hub: IMessageHub;
    dispatcher: IDispatcher;
    notificationHub: INotificationHub;
    scheduler?: SchedulerLike;
    lifespanMs?: number;
    cap?: number;
  }) {
    super({
      name: opts.name,
      hint: opts.hint,
      hub: opts.hub,
      dispatcher: opts.dispatcher,
    });
    this.#notificationHub = opts.notificationHub;
    this.#scheduler = opts.scheduler ?? asyncScheduler;
    this.#lifespanMs = opts.lifespanMs;
    this.#cap = opts.cap ?? NotificationsVM.DEFAULT_CAP;
  }

  get type(): ViewModelType {
    return ViewModelType.Component;
  }

  get hub(): IMessageHub {
    return this._hub;
  }

  /** Bounded list of currently-rendered notifications. */
  get visible(): readonly NotificationVM[] {
    return this.#visible;
  }

  get cap(): number {
    return this.#cap;
  }

  protected override _onConstruct(): void {
    super._onConstruct();
    this.#pendingSub = this.#notificationHub.pending.subscribe((list) => {
      this.#syncFromPending([...list]);
    });
  }

  protected override _onDestruct(): void {
    this.#pendingSub?.unsubscribe();
    this.#pendingSub = null;
    this.#clearVisible();
    super._onDestruct();
  }

  #syncFromPending(pending: Notification[]): void {
    // Add VMs for new pending notifications, respecting the cap.
    for (const n of pending) {
      if (this.#map.has(n)) continue;
      const vm = new NotificationVM(
        n,
        this.#notificationHub,
        this.#scheduler,
        this.#lifespanMs,
      );
      this.#map.set(n, vm);
      this.#visible.push(vm);
      while (this.#visible.length > this.#cap) {
        const [oldest] = this.#visible.splice(0, 1);
        if (!oldest) continue;
        for (const [k, v] of this.#map) {
          if (v === oldest) {
            this.#map.delete(k);
            break;
          }
        }
        oldest.dispose();
      }
    }
    // Remove VMs whose notifications are no longer pending.
    const stillPending = new Set<Notification>(pending);
    for (const [k, v] of [...this.#map]) {
      if (!stillPending.has(k)) {
        this.#map.delete(k);
        const idx = this.#visible.indexOf(v);
        if (idx >= 0) this.#visible.splice(idx, 1);
        v.dispose();
      }
    }
    this._hub.send(
      PropertyChangedMessage.create(this, this._name, "visible"),
    );
    this._raisePropertyChanged("visible");
  }

  #clearVisible(): void {
    for (const v of this.#visible) v.dispose();
    this.#visible.length = 0;
    this.#map.clear();
  }

  protected override _onDispose(): void {
    this.#pendingSub?.unsubscribe();
    this.#clearVisible();
    super._onDispose();
  }

  static builder(): NotificationsVMBuilder {
    return new NotificationsVMBuilder();
  }
}

export class NotificationsVMBuilder {
  #name: string | null = null;
  #hint = "";
  #hub: IMessageHub | null = null;
  #dispatcher: IDispatcher | null = null;
  #notificationHub: INotificationHub | null = null;
  #scheduler: SchedulerLike | null = null;
  #lifespanMs: number | undefined = undefined;
  #cap: number = NotificationsVM.DEFAULT_CAP;

  constructor(from?: NotificationsVMBuilder) {
    if (from) {
      this.#name = from.#name;
      this.#hint = from.#hint;
      this.#hub = from.#hub;
      this.#dispatcher = from.#dispatcher;
      this.#notificationHub = from.#notificationHub;
      this.#scheduler = from.#scheduler;
      this.#lifespanMs = from.#lifespanMs;
      this.#cap = from.#cap;
    }
  }

  name(value: string): NotificationsVMBuilder {
    const b = new NotificationsVMBuilder(this);
    b.#name = value;
    return b;
  }

  hint(value: string): NotificationsVMBuilder {
    const b = new NotificationsVMBuilder(this);
    b.#hint = value;
    return b;
  }

  services(hub: IMessageHub, dispatcher: IDispatcher): NotificationsVMBuilder {
    const b = new NotificationsVMBuilder(this);
    b.#hub = hub;
    b.#dispatcher = dispatcher;
    return b;
  }

  notificationHub(hub: INotificationHub): NotificationsVMBuilder {
    const b = new NotificationsVMBuilder(this);
    b.#notificationHub = hub;
    return b;
  }

  scheduler(scheduler: SchedulerLike): NotificationsVMBuilder {
    const b = new NotificationsVMBuilder(this);
    b.#scheduler = scheduler;
    return b;
  }

  lifespanMs(value: number): NotificationsVMBuilder {
    const b = new NotificationsVMBuilder(this);
    b.#lifespanMs = value;
    return b;
  }

  cap(value: number): NotificationsVMBuilder {
    const b = new NotificationsVMBuilder(this);
    b.#cap = value;
    return b;
  }

  build(): NotificationsVM {
    if (this.#name === null) throw new Error("name is required");
    if (this.#hub === null || this.#dispatcher === null)
      throw new Error("services are required");
    if (this.#notificationHub === null)
      throw new Error("notificationHub is required");
    return new NotificationsVM({
      name: this.#name,
      hint: this.#hint,
      hub: this.#hub,
      dispatcher: this.#dispatcher,
      notificationHub: this.#notificationHub,
      ...(this.#scheduler !== null ? { scheduler: this.#scheduler } : {}),
      ...(this.#lifespanMs !== undefined ? { lifespanMs: this.#lifespanMs } : {}),
      cap: this.#cap,
    });
  }
}
