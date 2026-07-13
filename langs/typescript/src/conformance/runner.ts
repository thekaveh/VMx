import { ConsumerConformanceExecutionError } from "./errors.js";
import { parseConsumerConformance } from "./schema.js";
import type {
  ConsumerConformanceAdapter,
  ConsumerConformanceCase,
  ConsumerConformanceCaseResult,
  ConsumerConformanceFactory,
  ConsumerConformanceReport,
  ConsumerConformanceStep,
  ConsumerConformanceSuite,
  JsonValue,
} from "./types.js";

export async function runConsumerConformanceCase(
  suite: ConsumerConformanceSuite,
  testCase: ConsumerConformanceCase,
  factory: ConsumerConformanceFactory,
): Promise<void> {
  const caseIndex = suite.cases.findIndex(
    (candidate) => candidate === testCase || candidate.id === testCase.id,
  );
  if (caseIndex < 0) {
    throw new ConsumerConformanceExecutionError({
      suiteId: suite.suite,
      caseId: testCase.id,
      path: "/cases",
      stepIndex: null,
      cause: new Error("test case does not belong to the supplied suite"),
    });
  }

  let adapter: ConsumerConformanceAdapter;
  try {
    adapter = await factory({
      suite,
      testCase,
      suiteFixture: suite.fixture,
      caseFixture: testCase.fixture,
    });
  } catch (cause) {
    throw new ConsumerConformanceExecutionError({
      suiteId: suite.suite,
      caseId: testCase.id,
      path: `/cases/${String(caseIndex)}/factory`,
      stepIndex: null,
      cause,
    });
  }

  let primaryError: ConsumerConformanceExecutionError | null = null;
  try {
    for (let stepIndex = 0; stepIndex < testCase.steps.length; stepIndex += 1) {
      const step = testCase.steps[stepIndex];
      if (step === undefined) continue;
      try {
        await executeStep(adapter, step);
      } catch (cause) {
        primaryError = new ConsumerConformanceExecutionError({
          suiteId: suite.suite,
          caseId: testCase.id,
          path: `/cases/${String(caseIndex)}/steps/${String(stepIndex)}`,
          stepIndex,
          cause,
        });
        break;
      }
    }
  } finally {
    try {
      await adapter.dispose();
    } catch (cause) {
      if (primaryError === null) {
        primaryError = new ConsumerConformanceExecutionError({
          suiteId: suite.suite,
          caseId: testCase.id,
          path: `/cases/${String(caseIndex)}/dispose`,
          stepIndex: null,
          cause,
        });
      } else {
        primaryError.attachTeardownCause(cause);
      }
    }
  }

  if (primaryError !== null) throw primaryError;
}

export async function runConsumerConformance(
  input: unknown,
  factory: ConsumerConformanceFactory,
): Promise<ConsumerConformanceReport> {
  const suite = parseConsumerConformance(input);
  const cases: ConsumerConformanceCaseResult[] = [];

  for (const testCase of suite.cases) {
    try {
      await runConsumerConformanceCase(suite, testCase, factory);
      cases.push({ id: testCase.id, status: "passed" });
    } catch (error) {
      const executionError = error instanceof ConsumerConformanceExecutionError
        ? error
        : new ConsumerConformanceExecutionError({
            suiteId: suite.suite,
            caseId: testCase.id,
            path: "/cases",
            stepIndex: null,
            cause: error,
          });
      cases.push({ id: testCase.id, status: "failed", error: executionError });
    }
  }

  const passed = cases.filter((result) => result.status === "passed").length;
  return {
    suite: suite.suite,
    total: cases.length,
    passed,
    failed: cases.length - passed,
    cases,
  };
}

async function executeStep(
  adapter: ConsumerConformanceAdapter,
  step: ConsumerConformanceStep,
): Promise<void> {
  switch (step.kind) {
    case "invoke":
      await adapter.invoke(step.operation, step.args ?? []);
      return;
    case "assert-state": {
      const resolved = resolveJsonPointer(adapter.snapshot(), step.path);
      if (!resolved.found) {
        throw new Error(`state path ${step.path || "<root>"} is not present`);
      }
      if (!jsonEquals(resolved.value, step.equals)) {
        throw new Error(
          `state assertion failed at ${step.path || "<root>"}: expected ${show(step.equals)}, received ${show(resolved.value)}`,
        );
      }
      return;
    }
    case "assert-messages": {
      const actual = adapter.drainMessages();
      if (!jsonEquals(actual, step.equals)) {
        throw new Error(
          `message assertion failed: expected ${show(step.equals)}, received ${show(actual)}`,
        );
      }
      return;
    }
  }
}

interface JsonPointerResult {
  readonly found: boolean;
  readonly value: JsonValue;
}

function resolveJsonPointer(root: JsonValue, pointer: string): JsonPointerResult {
  if (pointer === "") return { found: true, value: root };

  let current: JsonValue = root;
  for (const encoded of pointer.slice(1).split("/")) {
    const segment = encoded.split("~1").join("/").split("~0").join("~");
    if (Array.isArray(current)) {
      if (!/^(0|[1-9][0-9]*)$/.test(segment)) {
        return { found: false, value: null };
      }
      const index = Number(segment);
      if (index >= current.length) return { found: false, value: null };
      const next = current[index];
      if (next === undefined) return { found: false, value: null };
      current = next;
      continue;
    }
    if (
      current === null ||
      typeof current !== "object" ||
      !Object.prototype.hasOwnProperty.call(current, segment)
    ) {
      return { found: false, value: null };
    }
    const next = current[segment];
    if (next === undefined) return { found: false, value: null };
    current = next;
  }
  return { found: true, value: current };
}

function jsonEquals(left: JsonValue | readonly JsonValue[], right: JsonValue | readonly JsonValue[]): boolean {
  if (left === right) return true;
  if (left === null || right === null) return false;
  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) {
      return false;
    }
    return left.every((value, index) => {
      const other = right[index];
      return other !== undefined && jsonEquals(value, other);
    });
  }
  if (typeof left !== "object" || typeof right !== "object") return false;
  const leftObject = left as Record<string, JsonValue>;
  const rightObject = right as Record<string, JsonValue>;
  const leftKeys = Object.keys(leftObject);
  const rightKeys = Object.keys(rightObject);
  if (leftKeys.length !== rightKeys.length) return false;
  return leftKeys.every((key) => {
    const value = leftObject[key];
    const other = rightObject[key];
    return value !== undefined && other !== undefined && jsonEquals(value, other);
  });
}

function show(value: JsonValue | readonly JsonValue[]): string {
  return JSON.stringify(value);
}
