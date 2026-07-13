import { describe, expect, it, vi } from "vitest";
import {
  ConsumerConformanceExecutionError,
  parseConsumerConformance,
  runConsumerConformance,
  runConsumerConformanceCase,
  type ConsumerConformanceAdapter,
  type ConsumerConformanceFactory,
  type ConsumerConformanceSuite,
  type JsonObject,
  type JsonValue,
} from "../../../src/conformance/index.js";

describe("consumer conformance runner", () => {
  it("awaits operations in order before state and message assertions", async () => {
    const events: string[] = [];
    let count = 0;
    let messages: JsonObject[] = [];
    const dispose = vi.fn();
    const suite = makeSuite([
      { kind: "invoke", operation: "increment", args: [2] },
      { kind: "assert-state", path: "/model/count", equals: 2 },
      {
        kind: "assert-messages",
        equals: [{ type: "changed", value: 2 }],
      },
    ]);
    const factory: ConsumerConformanceFactory = () => ({
      async invoke(operation, args) {
        events.push(`${operation}:start`);
        await Promise.resolve();
        count += args[0] as number;
        messages.push({ type: "changed", value: count });
        events.push(`${operation}:finish`);
      },
      snapshot: () => ({ model: { count } }),
      drainMessages: () => {
        const drained = messages;
        messages = [];
        return drained;
      },
      dispose,
    });

    await runConsumerConformanceCase(suite, suite.cases[0]!, factory);

    expect(events).toEqual(["increment:start", "increment:finish"]);
    expect(dispose).toHaveBeenCalledTimes(1);
  });

  it("reports a state mismatch at the exact case step path", async () => {
    const suite = makeSuite([
      { kind: "assert-state", path: "/model/count", equals: 2 },
    ]);

    await expect(
      runConsumerConformanceCase(suite, suite.cases[0]!, () =>
        staticAdapter({ model: { count: 1 } }),
      ),
    ).rejects.toMatchObject({
      path: "/cases/0/steps/0",
      caseId: "DEMO-001",
      stepIndex: 0,
    });
  });

  it("reports a missing JSON Pointer segment without confusing it with null", async () => {
    const suite = makeSuite([
      { kind: "assert-state", path: "/model/missing", equals: null },
    ]);

    await expect(
      runConsumerConformanceCase(suite, suite.cases[0]!, () =>
        staticAdapter({ model: { value: null } }),
      ),
    ).rejects.toThrow(/\/model\/missing.*not present/);
  });

  it("reports exact ordered message mismatches", async () => {
    const suite = makeSuite([
      {
        kind: "assert-messages",
        equals: [{ type: "A" }, { type: "B" }],
      },
    ]);

    await expect(
      runConsumerConformanceCase(suite, suite.cases[0]!, () => ({
        ...staticAdapter({}),
        drainMessages: () => [{ type: "B" }, { type: "A" }],
      })),
    ).rejects.toThrow(/message assertion failed/);
  });

  it("reports factory failures at the factory path", async () => {
    const suite = makeSuite([
      { kind: "invoke", operation: "noop", args: [] },
    ]);
    const failure = new Error("factory exploded");

    try {
      await runConsumerConformanceCase(suite, suite.cases[0]!, () => {
        throw failure;
      });
      throw new Error("expected runner to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(ConsumerConformanceExecutionError);
      expect(error).toMatchObject({
        path: "/cases/0/factory",
        cause: failure,
      });
    }
  });

  it("disposes exactly once after operation failure", async () => {
    const suite = makeSuite([
      { kind: "invoke", operation: "fail", args: [] },
    ]);
    const dispose = vi.fn();
    const failure = new Error("operation exploded");

    await expect(
      runConsumerConformanceCase(suite, suite.cases[0]!, () => ({
        ...staticAdapter({}),
        invoke: () => {
          throw failure;
        },
        dispose,
      })),
    ).rejects.toMatchObject({ cause: failure, path: "/cases/0/steps/0" });
    expect(dispose).toHaveBeenCalledTimes(1);
  });

  it("preserves teardown failure alongside the primary failure", async () => {
    const suite = makeSuite([
      { kind: "invoke", operation: "fail", args: [] },
    ]);
    const operationFailure = new Error("operation exploded");
    const teardownFailure = new Error("dispose exploded");

    try {
      await runConsumerConformanceCase(suite, suite.cases[0]!, () => ({
        ...staticAdapter({}),
        invoke: () => {
          throw operationFailure;
        },
        dispose: () => {
          throw teardownFailure;
        },
      }));
      throw new Error("expected runner to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(ConsumerConformanceExecutionError);
      expect(error).toMatchObject({
        cause: operationFailure,
        teardownCause: teardownFailure,
      });
    }
  });

  it("reports teardown failure after otherwise successful steps", async () => {
    const suite = makeSuite([
      { kind: "assert-state", path: "/ready", equals: true },
    ]);
    const teardownFailure = new Error("dispose exploded");

    await expect(
      runConsumerConformanceCase(suite, suite.cases[0]!, () => ({
        ...staticAdapter({ ready: true }),
        dispose: () => {
          throw teardownFailure;
        },
      })),
    ).rejects.toMatchObject({
      cause: teardownFailure,
      path: "/cases/0/dispose",
      stepIndex: null,
    });
  });

  it("continues the suite and reports every case result", async () => {
    const suite = parseConsumerConformance({
      "$schema-version": "1.0.0",
      suite: "report-demo",
      cases: [
        {
          id: "PASS-001",
          fixture: { value: 1 },
          steps: [{ kind: "assert-state", path: "/value", equals: 1 }],
        },
        {
          id: "FAIL-001",
          fixture: { value: 2 },
          steps: [{ kind: "assert-state", path: "/value", equals: 3 }],
        },
      ],
    });
    const report = await runConsumerConformance(suite, ({ caseFixture }) =>
      staticAdapter(caseFixture ?? null),
    );

    expect(report).toMatchObject({
      suite: "report-demo",
      total: 2,
      passed: 1,
      failed: 1,
    });
    expect(report.cases.map((result) => result.status)).toEqual([
      "passed",
      "failed",
    ]);
    const failedCase = report.cases[1];
    expect(failedCase?.status).toBe("failed");
    if (failedCase?.status === "failed") {
      expect(failedCase.error.path).toBe("/cases/1/steps/0");
    }
  });
});

function makeSuite(
  steps: ConsumerConformanceSuite["cases"][number]["steps"],
): ConsumerConformanceSuite {
  return parseConsumerConformance({
    "$schema-version": "1.0.0",
    suite: "demo",
    fixture: { suite: true },
    cases: [{ id: "DEMO-001", fixture: { case: true }, steps }],
  });
}

function staticAdapter(snapshot: JsonValue): ConsumerConformanceAdapter {
  return {
    invoke: () => undefined,
    snapshot: () => snapshot,
    drainMessages: () => [],
    dispose: () => undefined,
  };
}
