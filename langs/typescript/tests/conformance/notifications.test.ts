// Conformance tests: NOTIF-001..016 — notification sub-package.
// See spec/16-notifications.md, ADR-0013, ADR-0031.

import { describe, expect, it } from "vitest";

import {
  ConfirmationVM,
  Notification,
  NotificationHub,
  NotificationReaction,
  NotificationType,
  NotificationVM,
  NullNotificationHub,
  makeConfirm,
  type INotificationHub,
} from "../../src/notifications/index.js";
import { FakeScheduler } from "../unit/notifications/fakeScheduler.js";

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

  it("NullNotificationHub.resolve is a no-op and pending stays empty", () => {
    const hub: INotificationHub = NullNotificationHub.INSTANCE;
    const n = new Notification(NotificationType.Notification, "stray");

    expect(() => hub.resolve(n, NotificationReaction.Approve)).not.toThrow();
    expect(() => hub.resolve(n, NotificationReaction.Reject)).not.toThrow();

    let observed: readonly Notification[] | undefined;
    const sub = hub.pending.subscribe((snapshot) => {
      observed = snapshot;
    });
    expect(observed).toEqual([]);
    sub.unsubscribe();
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
  it("NotificationVM opacity decays linearly from 1.0 to 0.0 over Lifespan", () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notification = new Notification(NotificationType.Notification, "hi");
    hub.post(notification);
    const sut = new NotificationVM(notification, hub, scheduler, 10_000);

    expect(sut.opacity).toBeCloseTo(1.0, 3);

    // Advance to 5 s
    scheduler.advanceTo(5_000);
    expect(sut.opacity).toBeCloseTo(0.5, 2);

    // Advance to 10 s
    scheduler.advanceTo(10_000);
    expect(sut.opacity).toBeCloseTo(0.0, 2);

    sut.dispose();
  });
});

describe("NOTIF-012", () => {
  it("NotificationVM auto-dismisses (resolves Approve) at expiry", async () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notification = new Notification(NotificationType.Notification, "auto");
    const task = hub.post(notification);
    const sut = new NotificationVM(notification, hub, scheduler, 10_000);

    expect(sut.isResolved).toBe(false);

    // Advance to 10 s (lifespan)
    scheduler.advanceTo(10_000);

    expect(sut.isResolved).toBe(true);
    await expect(task).resolves.toBe(NotificationReaction.Approve);

    sut.dispose();
  });
});

describe("NOTIF-013", () => {
  it("ConfirmationVM exposes ApproveCommand + RejectCommand resolving with the correct reaction", async () => {
    const scheduler = new FakeScheduler();

    // ApproveCommand resolves with Approve
    const hubA = new NotificationHub();
    const nA = new Notification(NotificationType.Confirmation, "approve me");
    const taskA = hubA.post(nA);
    const sutA = new ConfirmationVM(nA, hubA, scheduler);
    sutA.approveCommand.execute();
    expect(sutA.isResolved).toBe(true);
    await expect(taskA).resolves.toBe(NotificationReaction.Approve);
    sutA.dispose();

    // RejectCommand resolves with Reject
    const hubR = new NotificationHub();
    const nR = new Notification(NotificationType.Confirmation, "reject me");
    const taskR = hubR.post(nR);
    const sutR = new ConfirmationVM(nR, hubR, scheduler);
    sutR.rejectCommand.execute();
    expect(sutR.isResolved).toBe(true);
    await expect(taskR).resolves.toBe(NotificationReaction.Reject);
    sutR.dispose();
  });
});

describe("NOTIF-014", () => {
  it("Manual dismissCommand cancels the timer; subsequent ticks are no-ops", () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notification = new Notification(NotificationType.Notification, "dismiss");
    hub.post(notification);
    const sut = new NotificationVM(notification, hub, scheduler, 10_000);

    // Dismiss manually at t=0
    sut.dismissCommand.execute();
    expect(sut.isResolved).toBe(true);

    // Advance past lifespan — timer must not double-resolve
    scheduler.advanceTo(20_000);

    expect(sut.isResolved).toBe(true);
    let lastPending: readonly Notification[] = [];
    hub.pending.subscribe((p) => { lastPending = p; });
    expect(lastPending).not.toContain(notification);

    sut.dispose();
  });
});

describe("NOTIF-015", () => {
  it("Hub-side resolve() propagates to VM isResolved state", () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notification = new Notification(NotificationType.Notification, "hub resolves");
    hub.post(notification);
    const sut = new NotificationVM(notification, hub, scheduler, 60_000);

    expect(sut.isResolved).toBe(false);

    // External resolve via hub
    hub.resolve(notification, NotificationReaction.Approve);

    expect(sut.isResolved).toBe(true);

    // Advance past lifespan — timer must not re-fire
    scheduler.advanceTo(60_000);
    expect(sut.isResolved).toBe(true);

    sut.dispose();
  });
});

describe("NOTIF-016", () => {
  it("Deterministic behavior under injected VirtualTimeScheduler / fake clock", () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notification = new Notification(NotificationType.Notification, "tick");
    hub.post(notification);
    const sut = new NotificationVM(notification, hub, scheduler, 10_000);

    // t=0: opacity 1.0, not resolved
    expect(sut.opacity).toBeCloseTo(1.0, 3);
    expect(sut.isResolved).toBe(false);

    // t=5s: opacity 0.5
    scheduler.advanceTo(5_000);
    expect(sut.opacity).toBeCloseTo(0.5, 2);
    expect(sut.isResolved).toBe(false);

    // t=10s: auto-dismissed exactly at lifespan
    scheduler.advanceTo(10_000);
    expect(sut.isResolved).toBe(true);
    expect(sut.opacity).toBeCloseTo(0.0, 2);

    // No double-resolve: advancing further is a no-op
    scheduler.advanceTo(110_000);
    expect(sut.isResolved).toBe(true);

    sut.dispose();
  });
});

describe("NOTIF-017", () => {
  it("dispose resolves in-flight waiters with Pending, completes pending, and is idempotent", async () => {
    const hub = new NotificationHub();
    let completed = false;
    hub.pending.subscribe({ complete: () => (completed = true) });
    const task = hub.post(
      new Notification(NotificationType.Confirmation, "in-flight"),
    );

    hub.dispose();

    await expect(task).resolves.toBe(NotificationReaction.Pending);
    expect(completed).toBe(true);

    // Subsequent post resolves immediately with Pending and does not enqueue.
    await expect(
      hub.post(new Notification(NotificationType.Notification, "late")),
    ).resolves.toBe(NotificationReaction.Pending);

    // Subsequent resolve is a no-op; second dispose is a no-op.
    hub.resolve(
      new Notification(NotificationType.Notification, "ghost"),
      NotificationReaction.Approve,
    );
    hub.dispose();
  });
});
