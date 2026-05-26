/**
 * NotificationHub — async notification / confirmation hub.
 *
 * See spec/16-notifications.md and ADR-0013.
 */
import { BehaviorSubject, type Observable } from "rxjs";
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
}

export class NotificationHub implements INotificationHub {
  readonly #pending: Notification[] = [];
  readonly #waiters = new Map<Notification, Waiter>();
  readonly #subject = new BehaviorSubject<readonly Notification[]>([]);

  get pending(): Observable<readonly Notification[]> {
    return this.#subject.asObservable();
  }

  post(notification: Notification): Promise<NotificationReaction> {
    return new Promise<NotificationReaction>((resolve) => {
      this.#pending.push(notification);
      this.#waiters.set(notification, { resolve });
      this.#subject.next([...this.#pending]);
    });
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
    this.#subject.next([...this.#pending]);
    waiter.resolve(reaction);
  }
}
