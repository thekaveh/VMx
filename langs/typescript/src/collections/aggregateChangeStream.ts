import { Observable, Subscription } from "rxjs";
import type { Subscriber } from "rxjs";
import type { ComponentVMBase } from "../components/componentVMBase.js";
import type { ObservableMembershipSource } from "./observableMembership.js";

/** Provenance for one aggregate notification. */
export enum AggregateChangeReason {
  Initial = "initial",
  Membership = "membership",
  Item = "item",
  Batch = "batch",
}

/** Provenance-only aggregate envelope. */
export type AggregateChange<T extends object> =
  | {
      readonly reason:
        | AggregateChangeReason.Initial
        | AggregateChangeReason.Membership
        | AggregateChangeReason.Batch;
      readonly item?: never;
    }
  | {
      readonly reason: AggregateChangeReason.Item;
      readonly item: T;
    };

export interface AggregateObserveOptions {
  readonly emitInitial?: boolean;
}

interface Entry<T extends object> {
  readonly item: T;
  readonly epoch: number;
  refcount: number;
  subscription: Subscription | null;
  admitted: boolean;
  terminal: boolean;
  bufferedItems: number;
}

interface Registration<T extends object> {
  readonly observer: Subscriber<AggregateChange<T>>;
  active: boolean;
}

type WorkKind =
  | "structural"
  | "item"
  | "notification"
  | "error"
  | "completion";

interface Work<T extends object> {
  readonly kind: WorkKind;
  readonly recipients: readonly Registration<T>[];
  readonly coalesced: boolean;
  readonly change: AggregateChange<T> | null;
  entry: Entry<T> | null;
  readonly epoch: number;
  readonly error: unknown;
}

interface PendingChange<T extends object> {
  readonly change: AggregateChange<T>;
  readonly entry: Entry<T> | null;
  readonly epoch: number;
}

interface SnapshotPlan<T extends object> {
  readonly counts: Map<T, number>;
  readonly staged: Entry<T>[];
}

const noTerminalError = Symbol("no-terminal-error");

/**
 * Follows live source membership and fans in one selected stream per distinct
 * current object identity.
 */
export class AggregateChangeStream<T extends object> {
  readonly #source: ObservableMembershipSource<T>;
  readonly #observeItem: (item: T) => Observable<unknown>;
  readonly #entries = new Map<T, Entry<T>>();
  readonly #registrations: Registration<T>[] = [];
  readonly #work: Work<T>[] = [];

  #membershipSubscription: Subscription | null = null;
  #nextEpoch = 0;
  #structuralVersion = 0;
  #settingUp = true;
  #processing = false;
  #completed = false;
  #terminalError: unknown = noTerminalError;
  #batchDepth = 0;
  #batchDirty = false;
  readonly #batchRecipients = new Set<Registration<T>>();

  constructor(
    source: ObservableMembershipSource<T>,
    observeItem: (item: T) => Observable<unknown>,
  ) {
    const runtimeSource: unknown = source;
    const runtimeObserveItem: unknown = observeItem;
    if (runtimeSource == null) {
      throw new TypeError("source cannot be null or undefined");
    }
    if (runtimeObserveItem == null) {
      throw new TypeError("observeItem cannot be null or undefined");
    }
    this.#source = source;
    this.#observeItem = observeItem;

    try {
      const membershipSubscription: unknown = source.subscribeMembership(() => {
        this.#onMembershipChanged();
      });
      if (membershipSubscription == null) {
        throw new TypeError("membership source returned no subscription");
      }
      this.#membershipSubscription = membershipSubscription as Subscription;
      this.#initialize();
    } catch (error) {
      this.#failConstruction();
      throw error;
    }
  }

  /** Return the hot output with an optional atomic subscriber-local seed. */
  observe(options: AggregateObserveOptions = {}): Observable<AggregateChange<T>> {
    const emitInitial = options.emitInitial ?? false;
    return new Observable<AggregateChange<T>>((observer) =>
      this.#subscribe(observer, emitInitial),
    );
  }

  /** Run an action in a nested, ref-counted aggregate coalescing scope. */
  withBatch<TResult>(action: () => TResult): TResult {
    const runtimeAction: unknown = action;
    if (runtimeAction == null) {
      throw new TypeError("action cannot be null or undefined");
    }
    if (this.#completed || this.#terminalError !== noTerminalError) {
      throw new Error("AggregateChangeStream is no longer active");
    }
    this.#batchDepth++;

    let outcome:
      | { readonly succeeded: true; readonly value: TResult }
      | { readonly succeeded: false; readonly error: unknown };
    try {
      outcome = { succeeded: true, value: action() };
    } catch (error) {
      outcome = { succeeded: false, error };
    }

    let deliveryError: unknown = noTerminalError;
    try {
      this.#exitBatch();
    } catch (error) {
      deliveryError = error;
    }

    if (!outcome.succeeded) throw outcome.error;
    if (deliveryError !== noTerminalError) throw deliveryError;
    return outcome.value;
  }

  /** Detach owned subscriptions and complete output. Idempotent. */
  dispose(): void {
    if (this.#completed || this.#terminalError !== noTerminalError) return;
    this.#completed = true;
    this.#cleanupSubscriptions();
    this.#work.length = 0;
    const recipients = this.#currentRegistrations();
    this.#registrations.length = 0;
    if (recipients.length > 0) {
      this.#work.push(this.#makeWork("completion", recipients));
    }
    if (this.#startProcessing()) this.#processWork();
  }

  /** Observe the standard VM-local property-change stream. */
  static forComponents<TComponent extends ComponentVMBase>(
    source: ObservableMembershipSource<TComponent>,
  ): AggregateChangeStream<TComponent> {
    return new AggregateChangeStream(source, (item) => item.propertyChanged);
  }

  #initialize(): void {
    for (;;) {
      const version = this.#structuralVersion;
      const snapshot = this.#validatedSnapshot();
      if (version !== this.#structuralVersion) continue;

      const plan = this.#buildPlan(snapshot);
      try {
        this.#stageNewEntries(plan);
      } catch (error) {
        this.#disposeStaged(plan);
        throw error;
      }
      if (version !== this.#structuralVersion) {
        this.#disposeStaged(plan);
        continue;
      }

      this.#commitPlan(plan);
      if (version !== this.#structuralVersion) continue;
      this.#discardBufferedItems();
      this.#settingUp = false;
      return;
    }
  }

  #onMembershipChanged(): void {
    this.#structuralVersion++;
    const setupActivity = this.#settingUp;
    if (
      this.#completed ||
      this.#terminalError !== noTerminalError ||
      setupActivity
    ) {
      return;
    }

    const coalesced = this.#batchDepth > 0;
    const recipients = this.#currentRegistrations();
    if (coalesced) this.#admitBatchRecipients(recipients);
    this.#work.push(
      this.#makeWork("structural", recipients, {
        coalesced,
      }),
    );
    if (this.#startProcessing()) this.#processWork();
  }

  #onItem(entry: Entry<T>): void {
    const setupActivity = this.#settingUp;
    if (
      this.#completed ||
      this.#terminalError !== noTerminalError ||
      entry.terminal ||
      setupActivity
    ) {
      return;
    }
    if (!entry.admitted) {
      entry.bufferedItems++;
      return;
    }

    const coalesced = this.#batchDepth > 0;
    const recipients = this.#currentRegistrations();
    if (coalesced) this.#admitBatchRecipients(recipients);
    this.#work.push(
      this.#makeWork("item", recipients, {
        coalesced,
        entry,
        epoch: entry.epoch,
      }),
    );
    if (this.#startProcessing()) this.#processWork();
  }

  #onItemTerminal(entry: Entry<T>): void {
    if (
      this.#completed ||
      this.#terminalError !== noTerminalError ||
      entry.terminal
    ) {
      return;
    }
    entry.terminal = true;
    entry.bufferedItems = 0;
    this.#safeUnsubscribe(entry.subscription);
    entry.subscription = null;
  }

  #processWork(): void {
    let firstDeliveryError: unknown = noTerminalError;
    while (this.#work.length > 0) {
      const current = this.#work.shift();
      if (current === undefined) break;
      if (current.kind === "structural") {
        this.#processStructural(current);
        continue;
      }
      if (current.kind === "item") {
        this.#processItem(current);
        continue;
      }
      if (!this.#admitGuardedDelivery(current)) continue;
      try {
        this.#deliver(current);
      } catch (error) {
        if (firstDeliveryError === noTerminalError) firstDeliveryError = error;
      }
    }
    this.#processing = false;
    if (firstDeliveryError !== noTerminalError) throw firstDeliveryError;
  }

  #processStructural(work: Work<T>): void {
    if (this.#completed || this.#terminalError !== noTerminalError) return;
    try {
      for (;;) {
        const version = this.#structuralVersion;
        const snapshot = this.#validatedSnapshot();
        if (version !== this.#structuralVersion) continue;

        const plan = this.#buildPlan(snapshot);
        try {
          this.#stageNewEntries(plan);
        } catch (error) {
          this.#disposeStaged(plan);
          throw error;
        }
        if (version !== this.#structuralVersion) {
          this.#disposeStaged(plan);
          continue;
        }

        this.#commitPlan(plan);
        if (version !== this.#structuralVersion) continue;
        const changes: PendingChange<T>[] = [
          {
            change: { reason: AggregateChangeReason.Membership },
            entry: null,
            epoch: 0,
          },
        ];
        this.#appendBufferedItems(changes);
        this.#prependChanges(changes, work.coalesced, work.recipients);
        return;
      }
    } catch (error) {
      this.#failExisting(error);
    }
  }

  #processItem(work: Work<T>): void {
    const entry = work.entry;
    if (
      entry === null ||
      this.#completed ||
      this.#terminalError !== noTerminalError ||
      !entry.admitted ||
      entry.terminal ||
      entry.epoch !== work.epoch ||
      entry.refcount === 0
    ) {
      return;
    }
    this.#prependChanges(
      [
        {
          change: { reason: AggregateChangeReason.Item, item: entry.item },
          entry,
          epoch: work.epoch,
        },
      ],
      work.coalesced,
      work.recipients,
    );
  }

  #validatedSnapshot(): readonly T[] {
    const raw: unknown = this.#source.snapshot();
    if (raw == null) {
      throw new TypeError("membership source returned a null or undefined snapshot");
    }
    const snapshot = [...(raw as readonly unknown[])];
    for (const item of snapshot) {
      if (item == null) {
        throw new TypeError("membership snapshots cannot contain null or undefined items");
      }
    }
    return snapshot as readonly T[];
  }

  #buildPlan(snapshot: readonly T[]): SnapshotPlan<T> {
    const counts = new Map<T, number>();
    for (const item of snapshot) {
      counts.set(item, (counts.get(item) ?? 0) + 1);
    }
    return { counts, staged: [] };
  }

  #stageNewEntries(plan: SnapshotPlan<T>): void {
    for (const [item, refcount] of plan.counts) {
      if (this.#entries.has(item)) continue;
      const entry: Entry<T> = {
        item,
        epoch: ++this.#nextEpoch,
        refcount,
        subscription: null,
        admitted: false,
        terminal: false,
        bufferedItems: 0,
      };
      const selected = this.#observeItem(item) as
        | Observable<unknown>
        | null
        | undefined;
      if (selected == null) {
        throw new TypeError("observeItem returned null or undefined");
      }
      const subscription = selected.subscribe({
        next: () => this.#onItem(entry),
        error: () => this.#onItemTerminal(entry),
        complete: () => this.#onItemTerminal(entry),
      }) as Subscription | null | undefined;
      if (subscription == null) {
        throw new TypeError("selected stream returned no subscription");
      }
      entry.subscription = subscription;
      if (entry.terminal) {
        this.#safeUnsubscribe(entry.subscription);
        entry.subscription = null;
      }
      plan.staged.push(entry);
    }
  }

  #commitPlan(plan: SnapshotPlan<T>): void {
    for (const [item, existing] of [...this.#entries]) {
      const refcount = plan.counts.get(item);
      if (refcount !== undefined) {
        existing.refcount = refcount;
        continue;
      }
      existing.admitted = false;
      existing.refcount = 0;
      existing.bufferedItems = 0;
      this.#safeUnsubscribe(existing.subscription);
      existing.subscription = null;
      this.#entries.delete(item);
    }
    for (const staged of plan.staged) {
      staged.admitted = true;
      this.#entries.set(staged.item, staged);
    }
  }

  #appendBufferedItems(changes: PendingChange<T>[]): void {
    for (const entry of this.#entries.values()) {
      const bufferedItems = entry.terminal ? 0 : entry.bufferedItems;
      entry.bufferedItems = 0;
      for (let index = 0; index < bufferedItems; index++) {
        changes.push({
          change: { reason: AggregateChangeReason.Item, item: entry.item },
          entry,
          epoch: entry.epoch,
        });
      }
    }
  }

  #discardBufferedItems(): void {
    for (const entry of this.#entries.values()) entry.bufferedItems = 0;
  }

  #disposeStaged(plan: SnapshotPlan<T>): void {
    for (const staged of plan.staged) {
      staged.admitted = false;
      staged.bufferedItems = 0;
      this.#safeUnsubscribe(staged.subscription);
      staged.subscription = null;
    }
  }

  #prependChanges(
    changes: readonly PendingChange<T>[],
    coalesced: boolean,
    recipients: readonly Registration<T>[],
  ): void {
    if (changes.length === 0 || coalesced) return;
    if (recipients.length === 0) return;
    for (let index = changes.length - 1; index >= 0; index--) {
      const pending = changes[index];
      if (pending === undefined) continue;
      this.#work.unshift(
        this.#makeWork("notification", recipients, {
          change: pending.change,
          entry: pending.entry,
          epoch: pending.epoch,
        }),
      );
    }
  }

  #exitBatch(): void {
    this.#batchDepth--;
    if (this.#batchDepth !== 0 || !this.#batchDirty) return;
    this.#batchDirty = false;
    const recipients = [...this.#batchRecipients];
    this.#batchRecipients.clear();
    if (this.#completed || this.#terminalError !== noTerminalError) return;
    if (recipients.length === 0) return;
    this.#work.push(
      this.#makeWork("notification", recipients, {
        change: { reason: AggregateChangeReason.Batch },
      }),
    );
    if (this.#startProcessing()) this.#processWork();
  }

  #subscribe(
    observer: Subscriber<AggregateChange<T>>,
    emitInitial: boolean,
  ): (() => void) | void {
    if (this.#terminalError !== noTerminalError) {
      observer.error(this.#terminalError);
      return;
    }
    if (this.#completed) {
      observer.complete();
      return;
    }

    const registration: Registration<T> = { observer, active: true };
    this.#registrations.push(registration);
    if (emitInitial) {
      this.#work.push(
        this.#makeWork("notification", [registration], {
          change: { reason: AggregateChangeReason.Initial },
        }),
      );
      if (this.#startProcessing()) this.#processWork();
    }
    return () => this.#removeRegistration(registration);
  }

  #removeRegistration(registration: Registration<T>): void {
    if (!registration.active) return;
    registration.active = false;
    const index = this.#registrations.indexOf(registration);
    if (index >= 0) this.#registrations.splice(index, 1);
  }

  #failConstruction(): void {
    this.#cleanupSubscriptions();
    this.#completed = true;
    this.#work.length = 0;
  }

  #failExisting(error: unknown): void {
    if (this.#completed || this.#terminalError !== noTerminalError) return;
    this.#terminalError = error;
    this.#cleanupSubscriptions();
    this.#work.length = 0;
    const recipients = this.#currentRegistrations();
    this.#registrations.length = 0;
    if (recipients.length > 0) {
      this.#work.unshift(this.#makeWork("error", recipients, { error }));
    }
  }

  #cleanupSubscriptions(): void {
    this.#safeUnsubscribe(this.#membershipSubscription);
    this.#membershipSubscription = null;
    for (const entry of this.#entries.values()) {
      entry.admitted = false;
      entry.refcount = 0;
      entry.bufferedItems = 0;
      this.#safeUnsubscribe(entry.subscription);
      entry.subscription = null;
    }
    this.#entries.clear();
    this.#batchDirty = false;
    this.#batchRecipients.clear();
  }

  #admitBatchRecipients(recipients: readonly Registration<T>[]): void {
    this.#batchDirty = true;
    for (const registration of recipients) {
      if (registration.active && !registration.observer.closed) {
        this.#batchRecipients.add(registration);
      }
    }
  }

  #currentRegistrations(): readonly Registration<T>[] {
    return this.#registrations.filter((registration) => registration.active);
  }

  #startProcessing(): boolean {
    if (this.#processing || this.#work.length === 0) return false;
    this.#processing = true;
    return true;
  }

  #admitGuardedDelivery(work: Work<T>): boolean {
    const entry = work.entry;
    if (entry === null) return true;
    if (
      this.#completed ||
      this.#terminalError !== noTerminalError ||
      !entry.admitted ||
      entry.terminal ||
      entry.epoch !== work.epoch ||
      entry.refcount === 0
    ) {
      return false;
    }
    work.entry = null;
    return true;
  }

  #deliver(work: Work<T>): void {
    for (const registration of work.recipients) {
      if (!registration.active || registration.observer.closed) continue;
      if (work.kind === "notification") {
        if (work.change !== null) registration.observer.next(work.change);
      } else if (work.kind === "error") {
        registration.active = false;
        registration.observer.error(work.error);
      } else if (work.kind === "completion") {
        registration.active = false;
        registration.observer.complete();
      }
    }
  }

  #safeUnsubscribe(subscription: Subscription | null): void {
    if (subscription === null) return;
    try {
      subscription.unsubscribe();
    } catch {
      // Cleanup cannot replace a selector, body, or terminal failure.
    }
  }

  #makeWork(
    kind: WorkKind,
    recipients: readonly Registration<T>[],
    options: {
      readonly coalesced?: boolean;
      readonly change?: AggregateChange<T>;
      readonly entry?: Entry<T> | null;
      readonly epoch?: number;
      readonly error?: unknown;
    } = {},
  ): Work<T> {
    return {
      kind,
      recipients,
      coalesced: options.coalesced ?? false,
      change: options.change ?? null,
      entry: options.entry ?? null,
      epoch: options.epoch ?? 0,
      error: options.error,
    };
  }
}
