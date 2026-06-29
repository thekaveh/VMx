import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { MessageHub } from "../../src/index.js";
import type { IMessage } from "../../src/index.js";
import { allowRxUnhandledErrors } from "../setup.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

function makeMsg(id: string): IMessage {
  return { senderName: id, sender: {} };
}

// ---------------------------------------------------------------------------
// HUB-001
// ---------------------------------------------------------------------------

describe("HUB-001", () => {
  it("Send delivers to current subscribers synchronously", () => {
    const hub = new MessageHub();
    const received: IMessage[] = [];
    hub.messages.subscribe((m) => received.push(m));

    const msg = makeMsg("A");
    hub.send(msg);

    expect(received).toHaveLength(1);
    expect(received[0]).toBe(msg);
  });
});

// ---------------------------------------------------------------------------
// HUB-002
// ---------------------------------------------------------------------------

describe("HUB-002", () => {
  it("Late subscribers do not see prior messages", () => {
    const hub = new MessageHub();
    hub.send(makeMsg("A"));

    const received: IMessage[] = [];
    hub.messages.subscribe((m) => received.push(m));
    hub.send(makeMsg("B"));
    hub.send(makeMsg("C"));

    expect(received.map((m) => m.senderName)).toEqual(["B", "C"]);
  });
});

// ---------------------------------------------------------------------------
// HUB-003
// ---------------------------------------------------------------------------

describe("HUB-003", () => {
  it("Single-producer FIFO order", () => {
    const hub = new MessageHub();
    const received: string[] = [];
    hub.messages.subscribe((m) => received.push(m.senderName));

    hub.send(makeMsg("A"));
    hub.send(makeMsg("B"));
    hub.send(makeMsg("C"));

    expect(received).toEqual(["A", "B", "C"]);
  });
});

// ---------------------------------------------------------------------------
// HUB-004
// ---------------------------------------------------------------------------

describe("HUB-004", () => {
  it("Subscriber dispose during emit does not crash", () => {
    const hub = new MessageHub();
    const received: string[] = [];
    const sub = hub.messages.subscribe((m) => {
      received.push(m.senderName);
      sub.unsubscribe();
    });

    hub.send(makeMsg("A"));
    hub.send(makeMsg("B")); // must not crash; sub already disposed

    expect(received).toEqual(["A"]);
  });
});

// ---------------------------------------------------------------------------
// HUB-005
// ---------------------------------------------------------------------------

describe("HUB-005", () => {
  it("Multiple subscribers each observe every post-subscribe message", () => {
    const hub = new MessageHub();
    const r1: string[] = [];
    const r2: string[] = [];
    const r3: string[] = [];
    hub.messages.subscribe((m) => r1.push(m.senderName));
    hub.messages.subscribe((m) => r2.push(m.senderName));
    hub.messages.subscribe((m) => r3.push(m.senderName));

    hub.send(makeMsg("A"));
    hub.send(makeMsg("B"));

    expect(r1).toEqual(["A", "B"]);
    expect(r2).toEqual(["A", "B"]);
    expect(r3).toEqual(["A", "B"]);
  });
});

// ---------------------------------------------------------------------------
// HUB-006
// ---------------------------------------------------------------------------

describe("HUB-006", () => {
  it("Hub matches message-ordering fixture", () => {
    const raw = readFileSync(
      join(__dirname, "..", "..", "src", "fixtures", "message-ordering.json"),
      "utf-8",
    );
    const data = JSON.parse(raw) as {
      scenarios: Array<{
        id: string;
        producer_sends?: string[];
        producer_sends_before_subscribe?: string[];
        producer_sends_after_subscribe?: string[];
        subscriber_count?: number;
        expected_observed?: string[];
        expected_observed_per_subscriber?: string[];
        unsubscribe_after_first?: boolean;
      }>;
    };

    for (const scenario of data.scenarios) {
      const hub = new MessageHub();

      if (scenario.id === "single-producer-fifo") {
        const received: string[] = [];
        hub.messages.subscribe((m) => received.push(m.senderName));
        for (const id of scenario.producer_sends ?? []) hub.send(makeMsg(id));
        expect(received, scenario.id).toEqual(scenario.expected_observed);
      }

      if (scenario.id === "late-subscribe-no-replay") {
        for (const id of scenario.producer_sends_before_subscribe ?? []) hub.send(makeMsg(id));
        const received: string[] = [];
        hub.messages.subscribe((m) => received.push(m.senderName));
        for (const id of scenario.producer_sends_after_subscribe ?? []) hub.send(makeMsg(id));
        expect(received, scenario.id).toEqual(scenario.expected_observed);
      }

      if (scenario.id === "multiple-subscribers-same-message") {
        const buckets: string[][] = [];
        for (let i = 0; i < (scenario.subscriber_count ?? 0); i++) {
          const bucket: string[] = [];
          buckets.push(bucket);
          hub.messages.subscribe((m) => bucket.push(m.senderName));
        }
        for (const id of scenario.producer_sends ?? []) hub.send(makeMsg(id));
        for (const bucket of buckets) {
          expect(bucket, scenario.id).toEqual(scenario.expected_observed_per_subscriber);
        }
      }

      if (scenario.id === "unsubscribe-during-emit") {
        const received: string[] = [];
        const sub = hub.messages.subscribe((m) => {
          received.push(m.senderName);
          if (scenario.unsubscribe_after_first) sub.unsubscribe();
        });
        for (const id of scenario.producer_sends ?? []) hub.send(makeMsg(id));
        expect(received, scenario.id).toEqual(scenario.expected_observed);
      }
    }
  });
});

// ---------------------------------------------------------------------------
// HUB-007
// ---------------------------------------------------------------------------

describe("HUB-007", () => {
  it("Subscriber handler that raises does not break the hub", () => {
    // VMX-085: this test intentionally throws inside a subscriber; rxjs routes
    // that through reportUnhandledError on a macrotask. Opt this test in to the
    // scoped suppression instead of relying on a suite-wide global no-op.
    allowRxUnhandledErrors();
    const hub = new MessageHub();
    hub.messages.subscribe(() => {
      throw new Error("subscriber A blows up");
    });
    const received: IMessage[] = [];
    hub.messages.subscribe((m) => received.push(m));

    hub.send(makeMsg("msg1"));
    hub.send(makeMsg("msg2"));

    // Assert content + order (not just length), matching the Python/C#
    // HUB-007 corpus — a throwing subscriber must not drop, reorder, or
    // duplicate messages for the healthy subscriber.
    expect(received.map((m) => m.senderName)).toEqual(["msg1", "msg2"]);
  });
});
