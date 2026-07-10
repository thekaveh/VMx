import { BehaviorSubject } from "rxjs";
import { describe, expect, it } from "vitest";

import {
  AsyncRelayCommand,
  BatchUpdateHandle,
  ComponentVM,
  CompositeVM,
  ConstructionStatus,
  ConstructionStatusChangedMessage,
  FormVM,
  MessageHub,
  ModalVM,
  RxDispatcher,
  fromSources,
  type IBatchable,
} from "../../src/index.js";
import {
  Notification,
  NotificationHub,
  NotificationReaction,
  NotificationType,
} from "../../src/notifications/index.js";

describe("DISP-001", () => {
  it("makes repeated parent disposal observably idempotent", () => {
    const hub = new MessageHub();
    const dispatcher = RxDispatcher.immediate();
    const child = ComponentVM.builder().name("child").services(hub, dispatcher).build();
    const parent = CompositeVM.builder<ComponentVM>()
      .name("parent")
      .services(hub, dispatcher)
      .children(() => [child])
      .build();
    parent.construct();
    const disposed: string[] = [];
    hub.messages.subscribe((message) => {
      if (
        message instanceof ConstructionStatusChangedMessage &&
        message.status === ConstructionStatus.Disposed
      ) {
        disposed.push(message.senderName);
      }
    });

    parent.dispose();
    parent.dispose();

    expect(disposed.filter((name) => name === "child")).toHaveLength(1);
    expect(disposed.filter((name) => name === "parent")).toHaveLength(1);
  });
});

describe("DISP-002", () => {
  it("cancels one in-flight run when an async command is disposed repeatedly", async () => {
    let startedResolve!: () => void;
    const started = new Promise<void>((resolve) => {
      startedResolve = resolve;
    });
    let cancellations = 0;
    const command = AsyncRelayCommand.builder()
      .task(
        (signal) =>
          new Promise<void>((_, reject) => {
            startedResolve();
            signal.addEventListener(
              "abort",
              () => {
                cancellations += 1;
                reject(signal.reason as Error);
              },
              { once: true },
            );
          }),
      )
      .build();

    const run = command.executeAsync();
    await started;
    command.dispose();
    command.dispose();
    await expect(run).resolves.toBeUndefined();

    expect(cancellations).toBe(1);
    expect(command.canExecute()).toBe(false);
  });
});

describe("DISP-003", () => {
  it("completes a reentrantly disposed notification hub once", async () => {
    const hub = new NotificationHub();
    let completions = 0;
    hub.pending.subscribe({
      complete: () => {
        completions += 1;
        hub.dispose();
      },
    });
    const pending = hub.post(new Notification(NotificationType.Notification, "info"));

    hub.dispose();
    hub.dispose();

    await expect(pending).resolves.toBe(NotificationReaction.Pending);
    expect(completions).toBe(1);
  });
});

describe("DISP-004", () => {
  it("completes interaction owners once and preserves the first result", async () => {
    const form = new FormVM<number>({ initial: 1, persister: async () => {} });
    let completions = 0;
    form.onApproved.subscribe({ complete: () => (completions += 1) });
    form.dispose();
    form.dispose();
    expect(completions).toBe(1);

    const modal = new ModalVM("cancel");
    modal.dismiss("first");
    modal.dispose();
    modal.dispose();
    await expect(modal.completion).resolves.toBe("first");
  });
});

describe("DISP-005", () => {
  it("completes a reactive helper once and retains its last value", () => {
    const source = new BehaviorSubject(7);
    const property = fromSources<number>([source], (value) => value as number);
    let completions = 0;
    property.valueChanged.subscribe({ complete: () => (completions += 1) });

    property.dispose();
    property.dispose();
    source.next(8);

    expect(property.value).toBe(7);
    expect(completions).toBe(1);
  });
});

describe("DISP-006", () => {
  it("ends one batch exactly once", () => {
    const owner: IBatchable & { exits: number } = {
      exits: 0,
      _exitBatch() {
        this.exits += 1;
      },
    };
    const handle = new BatchUpdateHandle(owner);

    handle.dispose();
    handle.dispose();

    expect(owner.exits).toBe(1);
  });
});
