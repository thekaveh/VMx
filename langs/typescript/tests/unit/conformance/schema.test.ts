import { describe, expect, it } from "vitest";
import {
  ConsumerConformanceValidationError,
  parseConsumerConformance,
} from "../../../src/conformance/index.js";

const validSuite = {
  "$schema-version": "1.0.0",
  suite: "demo-vm",
  description: "A valid adapter suite",
  fixture: { initial: 1 },
  cases: [
    {
      id: "DEMO-001",
      description: "ordered operations and assertions",
      steps: [
        { kind: "invoke", operation: "increment", args: [2] },
        { kind: "assert-state", path: "/model/count", equals: 3 },
        {
          kind: "assert-messages",
          equals: [{ type: "PropertyChangedMessage", propertyName: "model" }],
        },
      ],
    },
  ],
} as const;

describe("consumer conformance schema", () => {
  it("parses a complete v1 suite", () => {
    const parsed = parseConsumerConformance(validSuite);

    expect(parsed.suite).toBe("demo-vm");
    expect(parsed.cases[0]?.id).toBe("DEMO-001");
    expect(parsed.cases[0]?.steps.map((step) => step.kind)).toEqual([
      "invoke",
      "assert-state",
      "assert-messages",
    ]);
  });

  it("rejects unsupported schema versions with the instance path", () => {
    expectValidationPath(
      { ...validSuite, "$schema-version": "2.0.0" },
      "/$schema-version",
    );
  });

  it("rejects a malformed invoke step at its missing operation path", () => {
    expectValidationPath(
      {
        ...validSuite,
        cases: [{ id: "DEMO-001", steps: [{ kind: "invoke", args: [] }] }],
      },
      "/cases/0/steps/0/operation",
    );
  });

  it("rejects consumer YAML fields instead of treating them as VMx schema", () => {
    expectValidationPath({ ...validSuite, vm: "DemoVM" }, "/vm");
  });
});

function expectValidationPath(input: unknown, expectedPath: string): void {
  try {
    parseConsumerConformance(input);
    throw new Error("expected validation to fail");
  } catch (error) {
    expect(error).toBeInstanceOf(ConsumerConformanceValidationError);
    const validationError = error as ConsumerConformanceValidationError;
    expect(validationError.issues.map((issue) => issue.path)).toContain(
      expectedPath,
    );
    expect(validationError.message).toContain(expectedPath);
  }
}
