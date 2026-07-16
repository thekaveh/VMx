import { describe, expect, it } from "vitest";

import {
  Notification,
  NotificationHub,
  NotificationReaction,
  NotificationType,
} from "../../../src/notifications/index.js";

describe("NotificationHub pending delivery", () => {
  it("queues reentrant snapshots behind the snapshot currently being delivered", () => {
    const hub = new NotificationHub();
    const first = new Notification(NotificationType.Notification, "first");
    const nested = new Notification(NotificationType.Notification, "nested");
    const trace: string[][] = [];
    let nestedPosted = false;

    hub.pending.subscribe((snapshot) => {
      if (snapshot.includes(first) && !nestedPosted) {
        nestedPosted = true;
        void hub.post(nested);
      }
    });
    hub.pending.subscribe((snapshot) => {
      trace.push(snapshot.map((notification) => notification.message));
    });

    void hub.post(first);

    expect(trace).toEqual([[], ["first"], ["first", "nested"]]);
  });

  it("replays current state without queued history to a reentrant late subscriber", () => {
    const hub = new NotificationHub();
    const first = new Notification(NotificationType.Notification, "first");
    const nested = new Notification(NotificationType.Notification, "nested");
    const lateTrace: string[][] = [];
    let attached = false;

    hub.pending.subscribe((snapshot) => {
      if (!snapshot.includes(first) || attached) return;
      attached = true;
      void hub.post(nested);
      hub.pending.subscribe((current) => {
        lateTrace.push(current.map((notification) => notification.message));
      });
    });

    void hub.post(first);

    expect(lateTrace).toEqual([["first", "nested"]]);
  });

  it("delivers an admitted snapshot before reentrant disposal completion", async () => {
    const hub = new NotificationHub();
    const notification = new Notification(NotificationType.Notification, "first");
    const trace: string[] = [];

    hub.pending.subscribe((snapshot) => {
      if (snapshot.includes(notification)) hub.dispose();
    });
    hub.pending.subscribe({
      next: (snapshot) => trace.push(snapshot.map((item) => item.message).join(",")),
      complete: () => trace.push("complete"),
    });

    const reaction = await hub.post(notification);

    expect(reaction).toBe(NotificationReaction.Pending);
    expect(trace).toEqual(["", "first", "complete"]);
  });
});
