// #1421: with asyncSelection, a selection delivery queued behind a throw from
// work that VMx did not queue, in one flush of the shared queueScheduler, still
// commits. The delivery is a counted foreground action (#1052, #1053), so the
// flush error's finalizer runs it. The outer schedule still throws the first
// error of the flush.

import { describe, expect, it } from "vitest";
import { queueScheduler } from "rxjs";
import {
  ComponentVM,
  CompositeVM,
  MessageHub,
  NullDispatcher,
  PropertyChangedMessage,
  RxDispatcher,
  type IDispatcher,
} from "../../src/index.js";
import { ManualDispatcher } from "../../src/testing/index.js";

function setup(dispatcher: IDispatcher) {
  const hub = new MessageHub();
  const a = ComponentVM.builder().name("a").services(hub, dispatcher).build();
  const b = ComponentVM.builder().name("b").services(hub, dispatcher).build();
  const root = CompositeVM.builder<ComponentVM>()
    .name("root")
    .services(hub, dispatcher)
    .asyncSelection(true)
    .children(() => [a, b])
    .build();
  root.construct();
  const changes: string[] = [];
  hub.messages.subscribe((message) => {
    if (message instanceof PropertyChangedMessage && message.sender === root) {
      changes.push(message.propertyName);
    }
  });
  return { root, a, b, changes };
}

/** Run `select` in one queueScheduler action behind a non-VMx throw. */
function behindForeignThrow(select: () => void): unknown {
  try {
    queueScheduler.schedule(() => {
      queueScheduler.schedule(() => {
        throw new Error("caller failed");
      });
      select();
    });
  } catch (error) {
    return error;
  }
  return undefined;
}

const dispatchers: Array<[string, () => IDispatcher]> = [
  ["RxDispatcher.immediate()", () => RxDispatcher.immediate()],
  ["NullDispatcher.INSTANCE", () => NullDispatcher.INSTANCE],
];

describe("an async selection behind a foreign throw in the same flush (#1421)", () => {
  for (const [label, make] of dispatchers) {
    it(`commits the current setter on ${label}`, () => {
      const { root, b, changes } = setup(make());

      const error = behindForeignThrow(() => {
        root.current = b;
      });

      expect((error as Error).message).toBe("caller failed");
      expect(root.current).toBe(b);
      expect(b.isCurrent).toBe(true);
      expect(changes.filter((name) => name === "current")).toHaveLength(1);
    });

    it(`commits selectComponent on ${label}`, () => {
      const { root, b, changes } = setup(make());

      const error = behindForeignThrow(() => root.selectComponent(b));

      expect((error as Error).message).toBe("caller failed");
      expect(root.current).toBe(b);
      expect(changes.filter((name) => name === "current")).toHaveLength(1);
    });

    it(`commits a change from a current child to null on ${label}`, () => {
      const { root, a, changes } = setup(make());
      root.current = a;
      expect(root.current).toBe(a);
      changes.length = 0;

      const error = behindForeignThrow(() => {
        root.current = null;
      });

      expect((error as Error).message).toBe("caller failed");
      expect(root.current).toBeNull();
      expect(a.isCurrent).toBe(false);
      expect(changes.filter((name) => name === "current")).toHaveLength(1);
    });
  }

  it("does not run a delivery that a disposed ManualDispatcher cancelled", () => {
    const dispatcher = new ManualDispatcher();
    const { root, a, b } = setup(dispatcher);
    dispatcher.flushAll();
    root.current = a;
    dispatcher.flushForeground();
    expect(root.current).toBe(a);

    root.current = b;
    dispatcher.dispose();

    expect(root.current).toBe(a);
    expect(b.isCurrent).toBe(false);
  });
});
