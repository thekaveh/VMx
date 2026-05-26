// Conformance tests: NULL-001..003 — null-object service convention.
// See spec/03-messages.md, spec/11-threading.md, ADR-0017.

import { describe, expect, it } from "vitest";

import {
  ConstructionStatus,
  ConstructionStatusChangedMessage,
  NullDispatcher,
  NullMessageHub,
  type IDispatcher,
  type IMessage,
  type IMessageHub,
} from "../../src/index.js";

describe("NULL-001", () => {
  it("NullMessageHub.send is no-op, messages is empty observable", () => {
    const hub = NullMessageHub.INSTANCE;
    const observed: IMessage[] = [];
    let completed = false;

    const sub = hub.messages.subscribe({
      next: (m) => observed.push(m),
      complete: () => {
        completed = true;
      },
    });

    for (let i = 0; i < 5; i++) {
      hub.send(
        ConstructionStatusChangedMessage.create(
          {},
          "x",
          ConstructionStatus.Constructed,
        ),
      );
    }

    expect(observed).toEqual([]);
    expect(completed).toBe(true);

    sub.unsubscribe();
  });
});

describe("NULL-002", () => {
  it("NullDispatcher schedules synchronously on the calling thread", () => {
    const dispatcher = NullDispatcher.INSTANCE;
    let fgRan = false;
    let bgRan = false;

    dispatcher.foreground.schedule(() => {
      fgRan = true;
    });
    expect(fgRan).toBe(true);

    dispatcher.background.schedule(() => {
      bgRan = true;
    });
    expect(bgRan).toBe(true);
  });
});

describe("NULL-003", () => {
  it("Null-object convention is satisfied for every core service contract", () => {
    // IMessageHub → NullMessageHub
    const hub: IMessageHub = NullMessageHub.INSTANCE;
    hub.send(
      ConstructionStatusChangedMessage.create(
        {},
        "x",
        ConstructionStatus.Destructed,
      ),
    );
    expect(hub.messages).toBeDefined();

    // IDispatcher → NullDispatcher
    const dispatcher: IDispatcher = NullDispatcher.INSTANCE;
    expect(dispatcher.foreground).toBeDefined();
    expect(dispatcher.background).toBeDefined();
  });
});
