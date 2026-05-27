/**
 * Notification primitives. See spec/16-notifications.md.
 */

export enum NotificationType {
  Error = "Error",
  Notification = "Notification",
  Confirmation = "Confirmation",
}

export enum NotificationReaction {
  Pending = "Pending",
  Approve = "Approve",
  Reject = "Reject",
}

export class Notification {
  constructor(
    readonly type: NotificationType,
    readonly message: string,
  ) {}
}
