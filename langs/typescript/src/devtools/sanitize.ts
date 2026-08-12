import type {
  DevtoolsJsonValue,
  DevtoolsSerializationLimits,
} from "./types.js";

interface ResolvedLimits {
  readonly maxDepth: number;
  readonly maxStringLength: number;
  readonly maxArrayLength: number;
  readonly maxObjectKeys: number;
}

const DEFAULT_LIMITS: ResolvedLimits = {
  maxDepth: 6,
  maxStringLength: 2_000,
  maxArrayLength: 100,
  maxObjectKeys: 100,
};

export function sanitizeDevtoolsValue(
  value: unknown,
  limits: DevtoolsSerializationLimits = {},
): DevtoolsJsonValue {
  const resolved: ResolvedLimits = {
    maxDepth: limits.maxDepth ?? DEFAULT_LIMITS.maxDepth,
    maxStringLength: limits.maxStringLength ?? DEFAULT_LIMITS.maxStringLength,
    maxArrayLength: limits.maxArrayLength ?? DEFAULT_LIMITS.maxArrayLength,
    maxObjectKeys: limits.maxObjectKeys ?? DEFAULT_LIMITS.maxObjectKeys,
  };
  const ancestors = new Set<object>();
  return visit(value, resolved, ancestors, 0);
}

function visit(
  value: unknown,
  limits: ResolvedLimits,
  ancestors: Set<object>,
  depth: number,
): DevtoolsJsonValue {
  if (value === null || typeof value === "boolean") return value;
  if (typeof value === "string") return truncate(value, limits.maxStringLength);
  if (typeof value === "number") return Number.isFinite(value) ? value : String(value);
  if (typeof value === "bigint") return `${String(value)}n`;
  if (typeof value === "undefined") return "[undefined]";
  if (typeof value === "function") return "[function]";
  if (typeof value === "symbol") return "[symbol]";
  if (typeof value !== "object") return "[unsupported]";
  if (depth >= limits.maxDepth) return "[max depth]";
  if (ancestors.has(value)) return "[circular]";

  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? "Invalid Date" : value.toISOString();
  }

  ancestors.add(value);
  try {
    if (Array.isArray(value)) {
      const count = Math.min(value.length, limits.maxArrayLength);
      const result: DevtoolsJsonValue[] = [];
      for (let index = 0; index < count; index++) {
        result.push(visit(value[index], limits, ancestors, depth + 1));
      }
      if (value.length > count) result.push(`[${String(value.length - count)} more]`);
      return result;
    }

    const result: Record<string, DevtoolsJsonValue> = {};
    const keys = Object.keys(value).slice(0, limits.maxObjectKeys);
    for (const key of keys) {
      try {
        result[key] = visit(
          (value as Record<string, unknown>)[key],
          limits,
          ancestors,
          depth + 1,
        );
      } catch {
        result[key] = "[unavailable]";
      }
    }
    const omitted = Object.keys(value).length - keys.length;
    if (omitted > 0) result["…"] = `[${String(omitted)} more keys]`;
    return result;
  } finally {
    ancestors.delete(value);
  }
}

function truncate(value: string, maximum: number): string {
  return value.length <= maximum ? value : `${value.slice(0, maximum)}…`;
}
