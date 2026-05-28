// Unit tests for NotificationVM — edge cases and implementation details.
// Conformance-level tests live in tests/conformance/notifications.test.ts.

import { describe, expect, it } from "vitest";

import {
  Notification,
  NotificationHub,
  NotificationReaction,
  NotificationType,
  NotificationVM,
  NullNotificationHub,
} from "../../../src/notifications/index.js";
import { FakeScheduler } from "./fakeScheduler.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeVm(lifespanMs = 60_000): {
  vm: NotificationVM;
  hub: NotificationHub;
  scheduler: FakeScheduler;
  notification: Notification;
} {
  const scheduler = new FakeScheduler();
  const hub = new NotificationHub();
  const notification = new Notification(NotificationType.Notification, "test");
  hub.post(notification);
  const vm = new NotificationVM(notification, hub, scheduler, lifespanMs);
  return { vm, hub, scheduler, notification };
}

// ---------------------------------------------------------------------------
// Construction
// ---------------------------------------------------------------------------

describe("NotificationVM construction", () => {
  it("initial opacity is 1.0", () => {
    const { vm } = makeVm();
    expect(vm.opacity).toBeCloseTo(1.0, 3);
    vm.dispose();
  });

  it("initial remainingMs equals lifespanMs", () => {
    const lifespanMs = 30_000;
    const { vm } = makeVm(lifespanMs);
    expect(vm.remainingMs).toBe(lifespanMs);
    vm.dispose();
  });

  it("initial isResolved is false", () => {
    const { vm } = makeVm();
    expect(vm.isResolved).toBe(false);
    vm.dispose();
  });

  it("default lifespanMs is 60 000 ms", () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notif = new Notification(NotificationType.Notification, "x");
    hub.post(notif);
    const vm = new NotificationVM(notif, hub, scheduler);
    expect(vm.lifespanMs).toBe(60_000);
    vm.dispose();
  });
});

// ---------------------------------------------------------------------------
// Opacity decay
// ---------------------------------------------------------------------------

describe("NotificationVM opacity decay", () => {
  it("opacity is 0 at lifespan", () => {
    const { vm, scheduler } = makeVm(10_000);
    scheduler.advanceTo(10_000);
    expect(vm.opacity).toBeCloseTo(0.0, 2);
    vm.dispose();
  });

  it("opacity is 0.5 at half lifespan", () => {
    const { vm, scheduler } = makeVm(10_000);
    scheduler.advanceTo(5_000);
    expect(vm.opacity).toBeCloseTo(0.5, 2);
    vm.dispose();
  });

  it("opacity does not go negative past lifespan", () => {
    const { vm, scheduler } = makeVm(5_000);
    scheduler.advanceTo(100_000);
    expect(vm.opacity).toBeGreaterThanOrEqual(0.0);
    vm.dispose();
  });

  it("opacity is 0 when lifespanMs is 0", () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notif = new Notification(NotificationType.Notification, "x");
    hub.post(notif);
    const vm = new NotificationVM(notif, hub, scheduler, 0);
    expect(vm.opacity).toBe(0.0);
    vm.dispose();
  });
});

// ---------------------------------------------------------------------------
// Auto-dismiss
// ---------------------------------------------------------------------------

describe("NotificationVM auto-dismiss", () => {
  it("auto-dismisses at lifespan expiry", () => {
    const { vm, scheduler } = makeVm(5_000);
    scheduler.advanceTo(5_000);
    expect(vm.isResolved).toBe(true);
    vm.dispose();
  });

  it("does not auto-dismiss before lifespan", () => {
    const { vm, scheduler } = makeVm(10_000);
    scheduler.advanceTo(9_000);
    expect(vm.isResolved).toBe(false);
    vm.dispose();
  });
});

// ---------------------------------------------------------------------------
// dismissCommand
// ---------------------------------------------------------------------------

describe("NotificationVM dismissCommand", () => {
  it("resolves with Approve", async () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notif = new Notification(NotificationType.Notification, "dismiss");
    const task = hub.post(notif);
    const vm = new NotificationVM(notif, hub, scheduler, 10_000);

    vm.dismissCommand.execute();

    expect(vm.isResolved).toBe(true);
    await expect(task).resolves.toBe(NotificationReaction.Approve);
    vm.dispose();
  });

  it("cancels the timer (no double-resolve)", () => {
    const { vm, scheduler } = makeVm(10_000);
    vm.dismissCommand.execute();
    expect(vm.isResolved).toBe(true);

    scheduler.advanceTo(100_000);
    expect(vm.isResolved).toBe(true);
    vm.dispose();
  });

  it("is idempotent", () => {
    const { vm } = makeVm();
    vm.dismissCommand.execute();
    vm.dismissCommand.execute(); // must not throw
    expect(vm.isResolved).toBe(true);
    vm.dispose();
  });
});

// ---------------------------------------------------------------------------
// NullNotificationHub
// ---------------------------------------------------------------------------

describe("NotificationVM with NullNotificationHub", () => {
  it("does not spuriously resolve on null hub empty pending", () => {
    const scheduler = new FakeScheduler();
    const hub = NullNotificationHub.INSTANCE;
    const notif = new Notification(NotificationType.Notification, "x");
    // Do NOT post — NullNotificationHub's pending emits [] once and completes.
    const vm = new NotificationVM(notif, hub, scheduler, 10_000);
    expect(vm.isResolved).toBe(false);
    vm.dispose();
  });
});
