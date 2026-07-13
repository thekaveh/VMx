export type JsonPrimitive = null | boolean | number | string;
export type JsonValue =
  | JsonPrimitive
  | JsonValue[]
  | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface ConsumerConformanceInvokeStep {
  readonly kind: "invoke";
  readonly operation: string;
  readonly args?: readonly JsonValue[];
}

export interface ConsumerConformanceStateStep {
  readonly kind: "assert-state";
  readonly path: string;
  readonly equals: JsonValue;
}

export interface ConsumerConformanceMessagesStep {
  readonly kind: "assert-messages";
  readonly equals: readonly JsonObject[];
}

export type ConsumerConformanceStep =
  | ConsumerConformanceInvokeStep
  | ConsumerConformanceStateStep
  | ConsumerConformanceMessagesStep;

export interface ConsumerConformanceCase {
  readonly id: string;
  readonly description?: string;
  readonly fixture?: JsonValue;
  readonly steps: readonly ConsumerConformanceStep[];
}

export interface ConsumerConformanceSuite {
  readonly "$schema-version": "1.0.0";
  readonly suite: string;
  readonly description?: string;
  readonly fixture?: JsonValue;
  readonly cases: readonly ConsumerConformanceCase[];
}

export interface ConsumerConformanceAdapter {
  invoke(
    operation: string,
    args: readonly JsonValue[],
  ): void | Promise<void>;
  snapshot(): JsonValue;
  drainMessages(): readonly JsonObject[];
  dispose(): void | Promise<void>;
}

export interface ConsumerConformanceFactoryContext {
  readonly suite: ConsumerConformanceSuite;
  readonly testCase: ConsumerConformanceCase;
  readonly suiteFixture: JsonValue | undefined;
  readonly caseFixture: JsonValue | undefined;
}

export type ConsumerConformanceFactory = (
  context: ConsumerConformanceFactoryContext,
) => ConsumerConformanceAdapter | Promise<ConsumerConformanceAdapter>;

export interface ConsumerConformancePassedCaseResult {
  readonly id: string;
  readonly status: "passed";
}

export interface ConsumerConformanceFailedCaseResult {
  readonly id: string;
  readonly status: "failed";
  readonly error: import("./errors.js").ConsumerConformanceExecutionError;
}

export type ConsumerConformanceCaseResult =
  | ConsumerConformancePassedCaseResult
  | ConsumerConformanceFailedCaseResult;

export interface ConsumerConformanceReport {
  readonly suite: string;
  readonly total: number;
  readonly passed: number;
  readonly failed: number;
  readonly cases: readonly ConsumerConformanceCaseResult[];
}
