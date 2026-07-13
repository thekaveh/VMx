import { parseConsumerConformance } from "./schema.js";
import type {
  ConsumerConformanceSuite,
  JsonObject,
  JsonValue,
} from "./types.js";

interface CommandTruthTableRow extends JsonObject {
  readonly id: string;
  readonly predicate: boolean | null;
  readonly task: string | null;
  readonly trigger_emits: boolean;
  readonly can_execute: boolean;
  readonly execute_invokes_task: boolean;
  readonly can_execute_changed_fires: boolean;
}

/** Adapt VMx's unchanged command truth-table fixture to the consumer v1 schema. */
export function adaptCommandTruthTableFixture(
  input: unknown,
): ConsumerConformanceSuite {
  const rows = readRows(input);
  return parseConsumerConformance({
    "$schema-version": "1.0.0",
    suite: "vmx-command-truthtable",
    description: "VMx RelayCommand truth-table fixture adapted without mutation",
    cases: rows.map((row) => ({
      id: row.id,
      fixture: row,
      steps: [
        { kind: "invoke", operation: "evaluate", args: [] },
        {
          kind: "assert-state",
          path: "/canExecute",
          equals: row.can_execute,
        },
        {
          kind: "assert-state",
          path: "/taskInvoked",
          equals: row.execute_invokes_task,
        },
        {
          kind: "assert-state",
          path: "/canExecuteChanged",
          equals: row.can_execute_changed_fires,
        },
      ],
    })),
  });
}

function readRows(input: unknown): readonly CommandTruthTableRow[] {
  if (!isObject(input) || input["$schema-version"] !== "1.0.0") {
    throw fixtureError("/$schema-version", "must equal 1.0.0");
  }
  const cases = input["cases"];
  if (!Array.isArray(cases)) {
    throw fixtureError("/cases", "must be an array");
  }
  return cases.map((row, index) => readRow(row, index));
}

function readRow(input: unknown, index: number): CommandTruthTableRow {
  const path = `/cases/${String(index)}`;
  if (!isObject(input)) throw fixtureError(path, "must be an object");

  requireString(input, "id", path);
  requireNullableBoolean(input, "predicate", path);
  requireNullableString(input, "task", path);
  requireBoolean(input, "trigger_emits", path);
  requireBoolean(input, "can_execute", path);
  requireBoolean(input, "execute_invokes_task", path);
  requireBoolean(input, "can_execute_changed_fires", path);
  return input as CommandTruthTableRow;
}

function requireString(
  input: Record<string, JsonValue>,
  key: string,
  path: string,
): void {
  if (typeof input[key] !== "string") {
    throw fixtureError(`${path}/${key}`, "must be a string");
  }
}

function requireBoolean(
  input: Record<string, JsonValue>,
  key: string,
  path: string,
): void {
  if (typeof input[key] !== "boolean") {
    throw fixtureError(`${path}/${key}`, "must be a boolean");
  }
}

function requireNullableBoolean(
  input: Record<string, JsonValue>,
  key: string,
  path: string,
): void {
  if (input[key] !== null && typeof input[key] !== "boolean") {
    throw fixtureError(`${path}/${key}`, "must be a boolean or null");
  }
}

function requireNullableString(
  input: Record<string, JsonValue>,
  key: string,
  path: string,
): void {
  if (input[key] !== null && typeof input[key] !== "string") {
    throw fixtureError(`${path}/${key}`, "must be a string or null");
  }
}

function isObject(value: unknown): value is Record<string, JsonValue> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function fixtureError(path: string, message: string): TypeError {
  return new TypeError(`Invalid VMx command truth-table fixture at ${path}: ${message}`);
}
