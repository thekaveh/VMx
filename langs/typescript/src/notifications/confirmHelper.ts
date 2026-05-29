/**
 * Bridge from INotificationHub Confirmation to the async predicate used
 * by ConfirmationDecoratorCommand.
 *
 * See spec/16-notifications.md §"Bridging command decorators".
 */
import {
  Notification,
  NotificationReaction,
  NotificationType,
} from "./notification.js";
import type { INotificationHub } from "./notificationHub.js";

export function makeConfirm(
  hub: INotificationHub,
  prompt: string,
): () => Promise<boolean> {
  return async () => {
    const notification = new Notification(NotificationType.Confirmation, prompt);
    const reaction = await hub.post(notification);
    return reaction === NotificationReaction.Approve;
  };
}
