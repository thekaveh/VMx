/**
 * Opt-in reverse child order for container destruct and dispose
 * (spec ch. 02 §6, ch. 06 §5, ch. 07 §2, ADR-0161).
 */
import { describe, expect, it } from "vitest";
import type { SchedulerLike } from "rxjs";
import {
  ComponentVM,
  ComponentVMBase,
  CompositeVM,
  CompositeVMOf,
  ConstructionStatus,
  ConstructionStatusChangedMessage,
  GroupVM,
  MessageHub,
  RxDispatcher,
} from "../../src/index.js";
import type { ChildOrder, IDispatcher } from "../../src/index.js";

const NAMES = ["a", "b", "c"] as const;

/** Records `<status>:<sender>` for every settled status message on `hub`. */
function record(hub: MessageHub): string[] {
  const log: string[] = [];
  hub.messages.subscribe((message) => {
    if (
      message instanceof ConstructionStatusChangedMessage &&
      (message.status === ConstructionStatus.Constructed ||
        message.status === ConstructionStatus.Destructed ||
        message.status === ConstructionStatus.Disposed)
    ) {
      log.push(`${ConstructionStatus[message.status]}:${message.senderName}`);
    }
  });
  return log;
}

function children(hub: MessageHub, dispatcher: IDispatcher, background = false): ComponentVM[] {
  return NAMES.map((name) =>
    ComponentVM.builder().name(name).services(hub, dispatcher).background(background).build());
}

type Make = (
  hub: MessageHub,
  dispatcher: IDispatcher,
  kids: ComponentVM[],
  order: ChildOrder | undefined,
) => ComponentVMBase;

function makeGroup(
  hub: MessageHub,
  dispatcher: IDispatcher,
  kids: ComponentVM[],
  order: ChildOrder | undefined,
): ComponentVMBase {
  let builder = GroupVM.builder<ComponentVM>()
    .name("parent").services(hub, dispatcher).children(() => kids);
  if (order !== undefined) builder = builder.destructOrder(order);
  return builder.build();
}

function makeGroupFromOptions(
  hub: MessageHub,
  dispatcher: IDispatcher,
  kids: ComponentVM[],
  order: ChildOrder | undefined,
): ComponentVMBase {
  return GroupVM.create<ComponentVM>({
    name: "parent",
    hub,
    dispatcher,
    children: () => kids,
    ...(order === undefined ? {} : { destructOrder: order }),
  });
}

function makeComposite(
  hub: MessageHub,
  dispatcher: IDispatcher,
  kids: ComponentVM[],
  order: ChildOrder | undefined,
): ComponentVMBase {
  let builder = CompositeVM.builder<ComponentVM>()
    .name("parent").services(hub, dispatcher).children(() => kids);
  if (order !== undefined) builder = builder.destructOrder(order);
  return builder.build();
}

function makeCompositeFromOptions(
  hub: MessageHub,
  dispatcher: IDispatcher,
  kids: ComponentVM[],
  order: ChildOrder | undefined,
): ComponentVMBase {
  return CompositeVM.create<ComponentVM>({
    name: "parent",
    hub,
    dispatcher,
    children: () => kids,
    ...(order === undefined ? {} : { destructOrder: order }),
  });
}

function makeModeledComposite(
  hub: MessageHub,
  dispatcher: IDispatcher,
  kids: ComponentVM[],
  order: ChildOrder | undefined,
): ComponentVMBase {
  let builder = CompositeVMOf.builder<number, ComponentVM>()
    .name("parent")
    .services(hub, dispatcher)
    .childrenModels(() => [0, 1, 2])
    .childModelToChildViewModel((index) => kids[index]!);
  if (order !== undefined) builder = builder.destructOrder(order);
  return builder.build();
}

const forward = (status: ConstructionStatus) =>
  NAMES.map((name) => `${ConstructionStatus[status]}:${name}`);
const backward = (status: ConstructionStatus) => forward(status).reverse();

function checkReverse(make: Make): void {
  const hub = new MessageHub();
  const dispatcher = RxDispatcher.immediate();
  const log = record(hub);
  const parent = make(hub, dispatcher, children(hub, dispatcher), "reverse");

  parent.construct();
  expect(log.splice(0)).toEqual([...forward(ConstructionStatus.Constructed), "Constructed:parent"]);

  parent.destruct();
  expect(log.splice(0)).toEqual([...backward(ConstructionStatus.Destructed), "Destructed:parent"]);

  parent.construct();
  log.splice(0);
  parent.reconstruct();
  expect(log.splice(0)).toEqual([
    ...backward(ConstructionStatus.Destructed),
    "Destructed:parent",
    ...forward(ConstructionStatus.Constructed),
    "Constructed:parent",
  ]);

  // LIFE-013: every child is disposed, last child first, before the parent.
  parent.dispose();
  expect(log.splice(0)).toEqual([...backward(ConstructionStatus.Disposed), "Disposed:parent"]);
}

function checkDefault(make: Make): void {
  const hub = new MessageHub();
  const dispatcher = RxDispatcher.immediate();
  const log = record(hub);
  const parent = make(hub, dispatcher, children(hub, dispatcher), undefined);

  parent.construct();
  parent.destruct();
  parent.dispose();

  expect(log).toEqual([
    ...forward(ConstructionStatus.Constructed),
    "Constructed:parent",
    ...forward(ConstructionStatus.Destructed),
    "Destructed:parent",
    ...forward(ConstructionStatus.Disposed),
    "Disposed:parent",
  ]);
}

/** Background children settle one at a time, so the walk waits on each in order. */
function checkReverseBackgroundWaits(make: Make): void {
  const work: Array<() => void> = [];
  const background = {
    schedule(action: () => void) {
      work.push(action);
      return { unsubscribe() {} };
    },
  };
  const dispatcher = new RxDispatcher(
    RxDispatcher.immediate().foreground,
    background as unknown as SchedulerLike,
  );
  const runAll = (): void => {
    while (work.length > 0) work.shift()!();
  };
  const hub = new MessageHub();
  const log = record(hub);
  const parent = make(hub, dispatcher, children(hub, dispatcher, true), "reverse");
  parent.construct();
  runAll();
  expect(parent.status).toBe(ConstructionStatus.Constructed);
  log.splice(0);

  parent.destruct();
  // The walk starts only the last child and waits for it to settle.
  expect(work).toHaveLength(1);
  runAll();
  expect(log).toEqual([...backward(ConstructionStatus.Destructed), "Destructed:parent"]);
}

describe("GRP-014", () => {
  it("reverse destructs and disposes children last first; construct stays in order", () => {
    checkReverse(makeGroup);
  });

  it("the create(options) destructOrder field gives the same order", () => {
    checkReverse(makeGroupFromOptions);
  });

  it("the default keeps insertion order for destruct and dispose", () => {
    checkDefault(makeGroup);
    checkDefault(makeGroupFromOptions);
  });

  it("reverse waits for background children last first", () => {
    checkReverseBackgroundWaits(makeGroup);
  });
});

describe("COMP-046", () => {
  it("reverse destructs and disposes children last first; construct stays in order", () => {
    checkReverse(makeComposite);
  });

  it("the create(options) destructOrder field gives the same order", () => {
    checkReverse(makeCompositeFromOptions);
  });

  it("the modeled composite builder gives the same order", () => {
    checkReverse(makeModeledComposite);
  });

  it("the default keeps insertion order for destruct and dispose", () => {
    checkDefault(makeComposite);
    checkDefault(makeCompositeFromOptions);
    checkDefault(makeModeledComposite);
  });

  it("reverse clears current before destructing children last first", () => {
    const hub = new MessageHub();
    const dispatcher = RxDispatcher.immediate();
    const kids = children(hub, dispatcher);
    const parent = CompositeVM.builder<ComponentVM>()
      .name("parent").services(hub, dispatcher).children(() => kids)
      .destructOrder("reverse").build();
    parent.construct();
    parent.selectComponent(kids[1]!);
    const log = record(hub);
    const currentAtFirstDestruct: Array<ComponentVM | null> = [];
    hub.messages.subscribe((message) => {
      if (
        message instanceof ConstructionStatusChangedMessage &&
        message.status === ConstructionStatus.Destructing &&
        currentAtFirstDestruct.length === 0 &&
        message.senderName !== "parent"
      ) {
        currentAtFirstDestruct.push(parent.current);
      }
    });

    parent.destruct();

    expect(currentAtFirstDestruct).toEqual([null]);
    expect(log).toEqual([...backward(ConstructionStatus.Destructed), "Destructed:parent"]);
  });

  it("reverse waits for background children last first", () => {
    checkReverseBackgroundWaits(makeComposite);
  });
});
