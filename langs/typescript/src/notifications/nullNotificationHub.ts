/**
 * NullNotificationHub — null-object variant per ADR-0017.
 */
import { of, type Observable } from "rxjs";
import {
  Notification,
  NotificationReaction,
} from "./notification.js";
import type { INotificationHub } from "./notificationHub.js";

export class NullNotificationHub implements INotificationHub {
  static readonly INSTANCE: NullNotificationHub = new NullNotificationHub();

  private constructor() {}

  readonly pending: Observable<readonly Notification[]> = of([]);

  post(_notification: Notification): Promise<NotificationReaction> {
    return Promise.resolve(NotificationReaction.Approve);
  }

  resolve(
    _notification: Notification,
    _reaction: NotificationReaction,
  ): void {
    // intentional no-op
  }
}
