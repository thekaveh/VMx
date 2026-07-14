/**
 * NotificationHub — async notification / confirmation hub.
 *
 * See spec/16-notifications.md and ADR-0013.
 */
import { Observable, Subject } from "rxjs";
import {
  Notification,
  NotificationReaction,
} from "./notification.js";

export interface INotificationHub {
  readonly pending: Observable<readonly Notification[]>;
  post(notification: Notification): Promise<NotificationReaction>;
  resolve(notification: Notification, reaction: NotificationReaction): void;
}

interface Waiter {
  resolve: (reaction: NotificationReaction) => void;
  promise: Promise<NotificationReaction>;
}

interface PendingSnapshot {
  readonly sequence: number;
  readonly notifications: readonly Notification[];
}

type PendingDelivery =
  | { readonly type: "snapshot"; readonly snapshot: PendingSnapshot }
  | { readonly type: "complete" };

export class NotificationHub implements INotificationHub {
  readonly #pending: Notification[] = [];
  readonly #waiters = new Map<Notification, Waiter>();
  readonly #subject = new Subject<PendingSnapshot>();
  readonly #deliveries: PendingDelivery[] = [];
  #sequence = 0;
  #deliveryHead = 0;
  #draining = false;
  #disposed = false;

  get pending(): Observable<readonly Notification[]> {
    // Subscriber-local replay preserves the BehaviorSubject-like contract
    // without exposing a stale in-flight snapshot. A listener that subscribes
    // from another listener's reentrant callback receives current state once,
    // then only mutation records admitted after it attached.
    return new Observable((subscriber) => {
      if (this.#disposed) {
        subscriber.complete();
        return;
      }

      const startSequence = this.#sequence;
      const initial = [...this.#pending];
      const subscription = this.#subject.subscribe({
        next: (snapshot) => {
          if (snapshot.sequence > startSequence) {
            subscriber.next(snapshot.notifications);
          }
        },
        complete: () => subscriber.complete(),
      });
      subscriber.next(initial);
      return () => subscription.unsubscribe();
    });
  }

  post(notification: Notification): Promise<NotificationReaction> {
    // Post after dispose resolves Pending and does not enqueue, matching
    // dispose()'s shutdown semantics (NOTIF-017).
    if (this.#disposed) return Promise.resolve(NotificationReaction.Pending);
    // Re-posting the same still-pending notification returns the existing
    // awaitable rather than orphaning the first waiter (double-post SHOULD,
    // ADR-0020 §2.3; mirrors the C# hub).
    const existing = this.#waiters.get(notification);
    if (existing) return existing.promise;
    let resolve!: (reaction: NotificationReaction) => void;
    const promise = new Promise<NotificationReaction>((res) => {
      resolve = res;
    });
    this.#pending.push(notification);
    this.#waiters.set(notification, { resolve, promise });
    this.#enqueueSnapshot();
    return promise;
  }

  resolve(
    notification: Notification,
    reaction: NotificationReaction,
  ): void {
    const waiter = this.#waiters.get(notification);
    if (!waiter) return;
    this.#waiters.delete(notification);
    const idx = this.#pending.indexOf(notification);
    if (idx >= 0) this.#pending.splice(idx, 1);
    this.#enqueueSnapshot();
    waiter.resolve(reaction);
  }

  /**
   * Resolve in-flight waiters with `Pending` and complete `pending`.
   * Idempotent (NOTIF-017). Mirrors the C# hub's shutdown semantics:
   * subsequent `post` calls resolve immediately with `Pending` without
   * enqueueing, and subsequent `resolve` calls are no-ops.
   */
  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    const waiters = [...this.#waiters.values()];
    this.#waiters.clear();
    this.#pending.length = 0;
    this.#sequence += 1;
    this.#enqueue({ type: "complete" });
    for (const waiter of waiters) waiter.resolve(NotificationReaction.Pending);
  }

  #enqueueSnapshot(): void {
    this.#sequence += 1;
    this.#enqueue({
      type: "snapshot",
      snapshot: {
        sequence: this.#sequence,
        notifications: [...this.#pending],
      },
    });
  }

  #enqueue(delivery: PendingDelivery): void {
    this.#deliveries.push(delivery);
    if (!this.#draining) this.#drain();
  }

  #drain(): void {
    // RxJS Subject delivery is reentrant. Serialize snapshots explicitly so a
    // callback-triggered post/resolve/dispose cannot make later observers see
    // a newer snapshot before the one currently being delivered.
    this.#draining = true;
    try {
      while (this.#deliveryHead < this.#deliveries.length) {
        const delivery = this.#deliveries[this.#deliveryHead++];
        if (delivery === undefined) continue;
        if (delivery.type === "complete") this.#subject.complete();
        else this.#subject.next(delivery.snapshot);
      }
    } finally {
      this.#deliveries.length = 0;
      this.#deliveryHead = 0;
      this.#draining = false;
    }
  }
}
