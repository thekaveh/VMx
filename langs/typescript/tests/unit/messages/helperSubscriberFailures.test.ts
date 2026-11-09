// Regression tests: a failing subscriber of a spec/03 §7.1/§7.2 hub helper
// stays attached and receives every matching message (ADR-0191, #1304).
// rxjs reports each failure through onUnhandledError.

import { config, type Observable } from "rxjs";
import { describe, expect, it } from "vitest";
import { MessageHub } from "../../../src/services/messageHub.js";
import { PropertyChangedMessage } from "../../../src/messages/propertyChanged.js";
import { propertyValueChangedMessagesFor } from "../../../src/messages/propertyValueChanged.js";
import { whenPropertyChanged } from "../../../src/messages/whenPropertyChanged.js";

class Source {
  count = 0;
}

/** Runs `act` with rxjs unhandled-error reports recorded, then drains them. */
async function withUnhandledErrors(act: () => void): Promise<unknown[]> {
  const unhandled: unknown[] = [];
  const previous = config.onUnhandledError;
  config.onUnhandledError = (error) => unhandled.push(error);
  try {
    act();
    await new Promise((resolve) => setTimeout(resolve, 0));
  } finally {
    config.onUnhandledError = previous;
  }
  return unhandled;
}

const helpers: ReadonlyArray<
  readonly [string, (hub: MessageHub, source: Source) => Observable<unknown>]
> = [
  [
    "propertyValueChangedMessagesFor",
    (hub, source) => propertyValueChangedMessagesFor(hub, source, "count"),
  ],
  ["whenPropertyChanged (one name)", (hub, source) => whenPropertyChanged(hub, source, "count")],
  [
    "whenPropertyChanged (name list)",
    (hub, source) => whenPropertyChanged(hub, source, ["count", "other"]),
  ],
];

describe("hub helper subscriber failures (ADR-0191)", () => {
  for (const [name, select] of helpers) {
    it(`${name}: a failing subscriber stays attached and receives 2 of 2`, async () => {
      const hub = new MessageHub();
      const source = new Source();
      let failing = 0;
      let healthy = 0;
      select(hub, source).subscribe(() => {
        failing++;
        throw new Error("helper subscriber failed");
      });
      select(hub, source).subscribe(() => healthy++);

      const unhandled = await withUnhandledErrors(() => {
        for (const value of [1, 2]) {
          source.count = value;
          expect(() =>
            hub.send(PropertyChangedMessage.create(source, "source", "count")),
          ).not.toThrow();
        }
      });

      expect(failing).toBe(2);
      expect(healthy).toBe(2);
      expect(unhandled).toHaveLength(2);
    });
  }
});
