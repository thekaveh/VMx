// Conformance tests: NOTIF-001..016 — notification sub-package.
// See spec/16-notifications.md, ADR-0013, ADR-0031.

import { describe, expect, it } from "vitest";

import {
  Notification,
  NotificationHub,
  NotificationReaction,
  NotificationType,
  NullNotificationHub,
  makeConfirm,
  type INotificationHub,
} from "../../src/notifications/index.js";

describe("NOTIF-001", () => {
  it("Post returns promise that resolves on Resolve", async () => {
    const hub = new NotificationHub();
    const n = new Notification(NotificationType.Notification, "info");
    const p = hub.post(n);
    hub.resolve(n, NotificationReaction.Approve);
    await expect(p).resolves.toBe(NotificationReaction.Approve);
  });
});

describe("NOTIF-002", () => {
  it("Post adds the notification to Pending", () => {
    const hub = new NotificationHub();
    let last: readonly Notification[] = [];
    hub.pending.subscribe((s) => {
      last = s;
    });
    const n = new Notification(NotificationType.Notification, "info");
    hub.post(n);
    expect(last).toContain(n);
  });
});

describe("NOTIF-003", () => {
  it("Resolve removes the notification from Pending", () => {
    const hub = new NotificationHub();
    let last: readonly Notification[] = [];
    hub.pending.subscribe((s) => {
      last = s;
    });
    const n = new Notification(NotificationType.Notification, "info");
    hub.post(n);
    hub.resolve(n, NotificationReaction.Approve);
    expect(last).not.toContain(n);
  });
});

describe("NOTIF-004", () => {
  it("NotificationType enum members", () => {
    expect(Object.values(NotificationType).sort()).toEqual(
      ["Confirmation", "Error", "Notification"],
    );
  });
});

describe("NOTIF-005", () => {
  it("NotificationReaction enum members", () => {
    expect(Object.values(NotificationReaction).sort()).toEqual(
      ["Approve", "Pending", "Reject"],
    );
  });
});

describe("NOTIF-006", () => {
  it("Resolved promise carries the reaction value", async () => {
    const hub = new NotificationHub();
    const n = new Notification(NotificationType.Notification, "info");
    const p = hub.post(n);
    hub.resolve(n, NotificationReaction.Reject);
    await expect(p).resolves.toBe(NotificationReaction.Reject);
  });
});

describe("NOTIF-007", () => {
  it("Confirmation Approve or Reject", async () => {
    const hub = new NotificationHub();
    const nA = new Notification(NotificationType.Confirmation, "x");
    const nR = new Notification(NotificationType.Confirmation, "y");
    const pA = hub.post(nA);
    const pR = hub.post(nR);
    hub.resolve(nA, NotificationReaction.Approve);
    hub.resolve(nR, NotificationReaction.Reject);
    await expect(pA).resolves.toBe(NotificationReaction.Approve);
    await expect(pR).resolves.toBe(NotificationReaction.Reject);
  });
});

describe("NOTIF-008", () => {
  it("Resolving a notification not in Pending is a no-op", () => {
    const hub = new NotificationHub();
    const orphan = new Notification(NotificationType.Notification, "stray");
    expect(() => hub.resolve(orphan, NotificationReaction.Approve)).not.toThrow();
  });
});

describe("NOTIF-009", () => {
  it("NullNotificationHub.post resolves Approve immediately", async () => {
    const hub: INotificationHub = NullNotificationHub.INSTANCE;
    const n = new Notification(NotificationType.Confirmation, "x");
    await expect(hub.post(n)).resolves.toBe(NotificationReaction.Approve);
  });
});

describe("NOTIF-010", () => {
  it("makeConfirm helper returns true iff Approve", async () => {
    const hub = new NotificationHub();
    const confirm = makeConfirm(hub, "ok?");

    // Auto-approve any pending
    const subA = hub.pending.subscribe((snapshot) => {
      for (const n of [...snapshot]) hub.resolve(n, NotificationReaction.Approve);
    });
    await expect(confirm()).resolves.toBe(true);
    subA.unsubscribe();

    const subR = hub.pending.subscribe((snapshot) => {
      for (const n of [...snapshot]) hub.resolve(n, NotificationReaction.Reject);
    });
    await expect(confirm()).resolves.toBe(false);
    subR.unsubscribe();
  });
});

describe("NOTIF-011", () => {
  it.todo(
    "NotificationVM opacity decays linearly from 1.0 to 0.0 over Lifespan — implement NotificationVM first (Substage 4B)",
  );
});

describe("NOTIF-012", () => {
  it.todo(
    "NotificationVM auto-dismisses (resolves Approve) at expiry — implement NotificationVM first (Substage 4B)",
  );
});

describe("NOTIF-013", () => {
  it.todo(
    "ConfirmationVM exposes ApproveCommand + RejectCommand resolving with the corresponding NotificationReaction — implement ConfirmationVM first (Substage 4B)",
  );
});

describe("NOTIF-014", () => {
  it.todo(
    "Manual DismissCommand cancels the timer; subsequent ticks no-op — implement NotificationVM first (Substage 4B)",
  );
});

describe("NOTIF-015", () => {
  it.todo(
    "Hub-side Resolve() propagates to VM IsResolved state — implement NotificationVM first (Substage 4B)",
  );
});

describe("NOTIF-016", () => {
  it.todo(
    "Deterministic behavior under injected TestScheduler / fake clock — implement NotificationVM first (Substage 4B)",
  );
});
