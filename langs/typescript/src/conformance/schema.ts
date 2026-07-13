import { Ajv2020, type ErrorObject } from "ajv/dist/2020.js";
import schema from "./schemas/consumer-conformance-v1.schema.json" with {
  type: "json",
};
import {
  ConsumerConformanceValidationError,
  type ConsumerConformanceValidationIssue,
} from "./errors.js";
import type { ConsumerConformanceSuite } from "./types.js";

export const consumerConformanceSchema = schema as Readonly<
  Record<string, unknown>
>;

const ajv = new Ajv2020({ allErrors: true, strict: true });
const validate = ajv.compile(consumerConformanceSchema);

export function parseConsumerConformance(
  input: unknown,
): ConsumerConformanceSuite {
  if (!validate(input)) {
    throw new ConsumerConformanceValidationError(
      (validate.errors ?? []).map(toValidationIssue),
    );
  }
  return input as ConsumerConformanceSuite;
}

function toValidationIssue(
  error: ErrorObject,
): ConsumerConformanceValidationIssue {
  const params = error.params as Record<string, unknown>;
  const missing =
    error.keyword === "required" && typeof params["missingProperty"] === "string"
      ? params["missingProperty"]
      : null;
  const additional =
    error.keyword === "additionalProperties" &&
    typeof params["additionalProperty"] === "string"
      ? params["additionalProperty"]
      : null;
  const property = missing ?? additional;
  const path = property === null
    ? error.instancePath || "/"
    : `${error.instancePath}/${escapePointerSegment(property)}`;

  return {
    path,
    keyword: error.keyword,
    message: error.message ?? "schema validation failed",
    schemaPath: error.schemaPath,
  };
}

function escapePointerSegment(value: string): string {
  return value.split("~").join("~0").split("/").join("~1");
}
