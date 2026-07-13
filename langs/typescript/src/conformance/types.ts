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
