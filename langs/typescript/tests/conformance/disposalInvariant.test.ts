import { BehaviorSubject } from "rxjs";
import { describe, expect, it } from "vitest";

import {
  AsyncRelayCommand,
  BatchUpdateHandle,
  ComponentVMBase,
  ViewModelType,
  CompositeVM,
  ConstructionStatus,
  ConstructionStatusChangedMessage,
  ExpandableState,
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

class OwningChild extends ComponentVMBase {
  readonly ownedRuns: { count: number } = { count: 0 };
  constructor(hub: MessageHub) {
    super({ name: "child", hint: "", hub, dispatcher: RxDispatcher.immediate() });
    this.own(() => (this.ownedRuns.count += 1));
  }
  get type(): ViewModelType {
    return ViewModelType.Component;
  }
}

class OwningParent extends CompositeVM<OwningChild> {
  readonly ownedRuns: { count: number } = { count: 0 };
  constructor(hub: MessageHub, child: OwningChild) {
    super({
      name: "parent",
      hint: "",
      hub,
      dispatcher: RxDispatcher.immediate(),
      childrenFactory: () => [child],
    });
    this.own(() => (this.ownedRuns.count += 1));
  }
}

describe("DISP-001", () => {
  it("makes repeated parent disposal observably idempotent", () => {
    const hub = new MessageHub();
    const child = new OwningChild(hub);
    const parent = new OwningParent(hub, child);
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
    expect(parent.status).toBe(ConstructionStatus.Disposed);
    expect(child.status).toBe(ConstructionStatus.Disposed);
    // Each owned disposal hook runs at most once (and, here, exactly once).
    expect(parent.ownedRuns.count).toBe(1);
    expect(child.ownedRuns.count).toBe(1);
  });
});

describe("DISP-002", () => {
  it("cancels one in-flight run when an async command is disposed repeatedly", async () => {
    let startedResolve!: () => void;
    const started = new Promise<void>((resolve) => {
      startedResolve = resolve;
    });
    let cancellations = 0;
    let runs = 0;
    const command = AsyncRelayCommand.builder()
      .task(
        (signal) =>
          new Promise<void>((_, reject) => {
            runs += 1;
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

    let errorCompletions = 0;
    let canExecuteCompletions = 0;
    const errors: unknown[] = [];
    command.errors.subscribe({
      next: (e) => errors.push(e),
      complete: () => (errorCompletions += 1),
    });
    command.canExecuteChanged.subscribe({ complete: () => (canExecuteCompletions += 1) });

    const run = command.executeAsync();
    await started;
    expect(command.isExecuting).toBe(true);
    command.dispose();
    command.dispose();
    await expect(run).resolves.toBeUndefined();

    expect(cancellations).toBe(1);
    // Non-executing terminal state.
    expect(command.isExecuting).toBe(false);
    expect(command.canExecute()).toBe(false);

    // Later execution attempts are inert.
    command.execute();
    await command.executeAsync();
    expect(runs).toBe(1);
    expect(command.isExecuting).toBe(false);

    // Terminal channels complete at most once.
    expect(errorCompletions).toBeLessThanOrEqual(1);
    expect(canExecuteCompletions).toBeLessThanOrEqual(1);
    expect(errors).toEqual([]);
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
    let persisted = 0;
    const form = new FormVM<number>({
      initial: 1,
      persister: () => {
        persisted += 1;
        return Promise.resolve();
      },
    });
    let completions = 0;
    const approvals: number[] = [];
    form.onApproved.subscribe({
      next: (v) => approvals.push(v),
      complete: () => (completions += 1),
    });
    form.dispose();
    form.dispose();
    expect(completions).toBe(1);

    // A disposed form is inert: setModel, deny, and approve are full no-ops
    // and the persister is never invoked.
    form.setModel(2);
    expect(form.model).toBe(1);
    expect(form.isDirty).toBe(false);
    form.denyCommand.execute();
    await form.approveAsync();
    form.approveCommand.execute();
    await Promise.resolve();
    expect(persisted).toBe(0);
    expect(approvals).toEqual([]);
    expect(form.model).toBe(1);

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

    const expansion = new ExpandableState(false);
    expansion.dispose();
    expansion.expand();
    expansion.collapse();
    expansion.toggleExpansion();
    expect(expansion.isExpanded).toBe(false);
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
