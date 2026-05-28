// Unit tests for ConfirmationVM — edge cases and implementation details.
// Conformance-level tests live in tests/conformance/notifications.test.ts.

import { describe, expect, it } from "vitest";

import {
  ConfirmationVM,
  Notification,
  NotificationHub,
  NotificationReaction,
  NotificationType,
} from "../../../src/notifications/index.js";
import { FakeScheduler } from "./fakeScheduler.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeConfirmationVm(lifespanMs?: number): {
  vm: ConfirmationVM;
  hub: NotificationHub;
  scheduler: FakeScheduler;
  notification: Notification;
} {
  const scheduler = new FakeScheduler();
  const hub = new NotificationHub();
  const notification = new Notification(NotificationType.Confirmation, "confirm?");
  hub.post(notification);
  const vm = new ConfirmationVM(notification, hub, scheduler, lifespanMs);
  return { vm, hub, scheduler, notification };
}

// ---------------------------------------------------------------------------
// Construction
// ---------------------------------------------------------------------------

describe("ConfirmationVM construction", () => {
  it("default lifespanMs is 300 000 ms", () => {
    const { vm } = makeConfirmationVm();
    expect(vm.lifespanMs).toBe(300_000);
    vm.dispose();
  });

  it("initial isResolved is false", () => {
    const { vm } = makeConfirmationVm();
    expect(vm.isResolved).toBe(false);
    vm.dispose();
  });

  it("initial opacity is 1.0", () => {
    const { vm } = makeConfirmationVm();
    expect(vm.opacity).toBeCloseTo(1.0, 3);
    vm.dispose();
  });
});

// ---------------------------------------------------------------------------
// No auto-dismiss on expiry
// ---------------------------------------------------------------------------

describe("ConfirmationVM auto-dismiss behavior", () => {
  it("does NOT auto-resolve on lifespan expiry", () => {
    const { vm, scheduler } = makeConfirmationVm(5_000);
    scheduler.advanceTo(5_000);
    expect(vm.isResolved).toBe(false);
    vm.dispose();
  });

  it("stays unresolved well past lifespan", () => {
    const { vm, scheduler } = makeConfirmationVm(5_000);
    scheduler.advanceTo(300_000);
    expect(vm.isResolved).toBe(false);
    vm.dispose();
  });
});

// ---------------------------------------------------------------------------
// ApproveCommand
// ---------------------------------------------------------------------------

describe("ConfirmationVM approveCommand", () => {
  it("resolves with Approve", async () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notif = new Notification(NotificationType.Confirmation, "approve?");
    const task = hub.post(notif);
    const vm = new ConfirmationVM(notif, hub, scheduler);

    vm.approveCommand.execute();
    expect(vm.isResolved).toBe(true);
    await expect(task).resolves.toBe(NotificationReaction.Approve);
    vm.dispose();
  });
});

// ---------------------------------------------------------------------------
// RejectCommand
// ---------------------------------------------------------------------------

describe("ConfirmationVM rejectCommand", () => {
  it("resolves with Reject", async () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notif = new Notification(NotificationType.Confirmation, "reject?");
    const task = hub.post(notif);
    const vm = new ConfirmationVM(notif, hub, scheduler);

    vm.rejectCommand.execute();
    expect(vm.isResolved).toBe(true);
    await expect(task).resolves.toBe(NotificationReaction.Reject);
    vm.dispose();
  });
});

// ---------------------------------------------------------------------------
// dismissCommand (inherited)
// ---------------------------------------------------------------------------

describe("ConfirmationVM dismissCommand (inherited)", () => {
  it("resolves with Approve via dismiss", async () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notif = new Notification(NotificationType.Confirmation, "dismiss");
    const task = hub.post(notif);
    const vm = new ConfirmationVM(notif, hub, scheduler);

    vm.dismissCommand.execute();
    expect(vm.isResolved).toBe(true);
    await expect(task).resolves.toBe(NotificationReaction.Approve);
    vm.dispose();
  });
});

// ---------------------------------------------------------------------------
// Idempotency
// ---------------------------------------------------------------------------

describe("ConfirmationVM idempotency", () => {
  it("approve then reject: first wins", async () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notif = new Notification(NotificationType.Confirmation, "x");
    const task = hub.post(notif);
    const vm = new ConfirmationVM(notif, hub, scheduler);

    vm.approveCommand.execute();
    vm.rejectCommand.execute(); // no-op
    await expect(task).resolves.toBe(NotificationReaction.Approve);
    vm.dispose();
  });

  it("reject then approve: first wins", async () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notif = new Notification(NotificationType.Confirmation, "x");
    const task = hub.post(notif);
    const vm = new ConfirmationVM(notif, hub, scheduler);

    vm.rejectCommand.execute();
    vm.approveCommand.execute(); // no-op
    await expect(task).resolves.toBe(NotificationReaction.Reject);
    vm.dispose();
  });
});
