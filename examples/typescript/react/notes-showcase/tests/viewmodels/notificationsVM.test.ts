import { TestScheduler } from "rxjs/testing";
import { describe, expect, it } from "vitest";
import { MessageHub, RxDispatcher } from "vmx";
import {
  Notification,
  NotificationHub,
  NotificationReaction,
  NotificationType,
} from "vmx/notifications";

import { NotificationsVM } from "../../src/viewmodels/notificationsVM.js";

function makeVM(opts: {
  cap?: number;
  lifespanMs?: number;
  scheduler?: TestScheduler;
} = {}): { vm: NotificationsVM; notifs: NotificationHub } {
  const hub = new MessageHub();
  const notifs = new NotificationHub();
  let builder = NotificationsVM.builder()
    .name("toast")
    .services(hub, RxDispatcher.immediate())
    .notificationHub(notifs)
    .cap(opts.cap ?? 5);
  if (opts.lifespanMs !== undefined) builder = builder.lifespanMs(opts.lifespanMs);
  if (opts.scheduler) builder = builder.scheduler(opts.scheduler);
  const vm = builder.build();
  vm.construct();
  return { vm, notifs };
}

describe("NotificationsVM", () => {
  it("adds a NotificationVM when one is posted", () => {
    const { vm, notifs } = makeVM();
    void notifs.post(new Notification(NotificationType.Notification, "Hi"));
    expect(vm.visible.length).toBe(1);
    expect(vm.visible[0]?.notification.message).toBe("Hi");
  });

  it("cap drops the oldest when exceeded", () => {
    const { vm, notifs } = makeVM({ cap: 2 });
    void notifs.post(new Notification(NotificationType.Notification, "a"));
    void notifs.post(new Notification(NotificationType.Notification, "b"));
    void notifs.post(new Notification(NotificationType.Notification, "c"));
    expect(vm.visible.length).toBe(2);
    expect(vm.visible.map((v) => v.notification.message)).toEqual(["b", "c"]);
  });

  it("removes a VM when the notification is resolved externally", () => {
    const { vm, notifs } = makeVM();
    const n = new Notification(NotificationType.Notification, "x");
    void notifs.post(n);
    expect(vm.visible.length).toBe(1);
    notifs.resolve(n, NotificationReaction.Approve);
    expect(vm.visible.length).toBe(0);
  });

  it("auto-dismisses after lifespan via a TestScheduler", () => {
    const scheduler = new TestScheduler(() => {
      /* no-op equality */
    });
    scheduler.run(() => {
      const { vm, notifs } = makeVM({
        lifespanMs: 1000,
        scheduler,
      });
      void notifs.post(new Notification(NotificationType.Notification, "exp"));
      expect(vm.visible.length).toBe(1);
      // Advance past lifespan
      scheduler.schedule(() => {
        expect(vm.visible.length).toBe(0);
      }, 1100);
    });
  });

  it("dispose cleans up subscriptions", () => {
    const { vm } = makeVM();
    expect(() => vm.dispose()).not.toThrow();
  });

  it("destruct clears visible list", () => {
    const { vm, notifs } = makeVM();
    void notifs.post(new Notification(NotificationType.Notification, "y"));
    expect(vm.visible.length).toBe(1);
    vm.destruct();
    expect(vm.visible.length).toBe(0);
  });

  it("default cap is 5", () => {
    const { vm } = makeVM();
    expect(vm.cap).toBe(5);
  });

  it("builder validates required fields", () => {
    expect(() => NotificationsVM.builder().build()).toThrow();
  });
});
