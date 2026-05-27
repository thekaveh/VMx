// VMx notification / confirmation hub.
// Sub-path export: `import { ... } from "vmx/notifications"`.
// See spec/16-notifications.md and ADR-0013.

export { NotificationType } from "./notification.js";
export { NotificationReaction } from "./notification.js";
export { Notification } from "./notification.js";
export type { INotificationHub } from "./notificationHub.js";
export { NotificationHub } from "./notificationHub.js";
export { NullNotificationHub } from "./nullNotificationHub.js";
export { makeConfirm } from "./confirmHelper.js";
