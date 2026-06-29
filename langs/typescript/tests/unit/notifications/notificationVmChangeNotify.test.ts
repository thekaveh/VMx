/**
 * VMX-135 regression — NotificationVM exposes a `propertyChanged` stream so a
 * binding view repaints the decaying state. `isResolved` always emits on
 * resolution; with a `tickIntervalMs` the time-varying `remainingMs`/`opacity`
 * emit periodically while the notification fades.
 */
import { describe, expect, it } from "vitest";

import {
  ConfirmationVM,
  Notification,
  NotificationHub,
  NotificationType,
  NotificationVM,
} from "../../../src/notifications/index.js";
import { FakeScheduler } from "./fakeScheduler.js";

describe("VMX-135: NotificationVM change-notification", () => {
  it("raises propertyChanged for decay when a tick interval is supplied", () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notification = new Notification(NotificationType.Notification, "fade");
    hub.post(notification);
    const vm = new NotificationVM(notification, hub, scheduler, 10_000, 1_000);

    const changed: string[] = [];
    vm.propertyChanged.subscribe((name) => changed.push(name));

    scheduler.advanceBy(3_000); // three decay ticks

    expect(changed).toContain("opacity");
    expect(changed).toContain("remainingMs");
    vm.dispose();
  });

  it("raises isResolved on dismiss even without a tick interval", () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notification = new Notification(NotificationType.Notification, "resolve");
    hub.post(notification);
    const vm = new NotificationVM(notification, hub, scheduler, 10_000);

    const changed: string[] = [];
    vm.propertyChanged.subscribe((name) => changed.push(name));

    vm.dismissCommand.execute();

    expect(changed).toContain("isResolved");
    vm.dispose();
  });

  it("is poll-only for decay when no tick interval is supplied", () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notification = new Notification(NotificationType.Notification, "poll");
    hub.post(notification);
    const vm = new NotificationVM(notification, hub, scheduler, 10_000);

    let decayChanges = 0;
    vm.propertyChanged.subscribe((name) => {
      if (name === "opacity" || name === "remainingMs") decayChanges++;
    });

    scheduler.advanceBy(5_000); // within lifespan, not yet resolved

    expect(decayChanges).toBe(0);
    expect(vm.isResolved).toBe(false);
    vm.dispose();
  });

  it("ConfirmationVM forwards the tick interval", () => {
    const scheduler = new FakeScheduler();
    const hub = new NotificationHub();
    const notification = new Notification(NotificationType.Confirmation, "confirm");
    hub.post(notification);
    const vm = new ConfirmationVM(notification, hub, scheduler, 10_000, 1_000);

    let sawOpacity = false;
    vm.propertyChanged.subscribe((name) => {
      if (name === "opacity") sawOpacity = true;
    });

    scheduler.advanceBy(2_000);

    expect(sawOpacity).toBe(true);
    vm.dispose();
  });
});
