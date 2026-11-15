/**
 * Clone diagnostics for FormVM snapshots (internal).
 *
 * A FormVM snapshot is a structured clone of the domain model. These helpers
 * find the top-level field that cannot be cloned and build the error that
 * FormVM raises for it. Nothing here is part of the public API; the package
 * index does not export this module.
 */

export type SnapshotPhase =
  | "construction"
  | "approve snapshot advance"
  | "approve reset model"
  | "approve reset snapshot"
  | "deny/revert";

function hasReachableEnumerableAccessor(
  value: unknown,
  seen = new Set<object>(),
): boolean {
  if ((typeof value !== "object" && typeof value !== "function") || value === null) {
    return false;
  }

  const object = value;
  if (seen.has(object)) return false;
  seen.add(object);

  let descriptors: PropertyDescriptorMap;
  try {
    descriptors = Object.getOwnPropertyDescriptors(object);
  } catch {
    return true;
  }

  // Structured clone traverses enumerable string-keyed properties but ignores
  // symbol-keyed properties. Read descriptor values only; never invoke getters.
  for (const key of Object.keys(descriptors)) {
    const descriptor = descriptors[key];
    if (descriptor?.enumerable !== true) continue;
    if (!("value" in descriptor)) return true;
    if (hasReachableEnumerableAccessor(descriptor.value, seen)) return true;
  }

  try {
    // Structured clone follows engine-owned, non-enumerable Error slots such
    // as `cause`; omit localization rather than risk re-running nested accessors.
    if (value instanceof Error) {
      return true;
    } else if (value instanceof Map) {
      for (const [key, entryValue] of Map.prototype.entries.call(value)) {
        if (hasReachableEnumerableAccessor(key, seen)) return true;
        if (hasReachableEnumerableAccessor(entryValue, seen)) return true;
      }
    } else if (value instanceof Set) {
      for (const entryValue of Set.prototype.values.call(value)) {
        if (hasReachableEnumerableAccessor(entryValue, seen)) return true;
      }
    }
  } catch {
    return true;
  }

  return false;
}

function findUncloneableTopLevelField(model: unknown): string | undefined {
  if ((typeof model !== "object" && typeof model !== "function") || model === null) {
    return undefined;
  }

  let descriptors: PropertyDescriptorMap;
  try {
    descriptors = Object.getOwnPropertyDescriptors(model);
  } catch {
    // Proxies may reject descriptor inspection. Context is still useful even
    // when safe field localization is impossible.
    return undefined;
  }

  if (hasReachableEnumerableAccessor(model)) return undefined;

  for (const key of Object.keys(descriptors)) {
    const descriptor = descriptors[key];
    if (descriptor?.enumerable !== true || !("value" in descriptor)) continue;
    try {
      structuredClone(descriptor.value);
    } catch {
      return key;
    }
  }
  return undefined;
}

export function defaultSnapshotError(
  model: unknown,
  phase: SnapshotPhase,
  cause: unknown,
): Error {
  const field = findUncloneableTopLevelField(model);
  const fieldContext = field === undefined
    ? ""
    : ` for top-level field ${JSON.stringify(field)}`;
  return new Error(
    `FormVM default structuredClone snapshot failed during ${phase}${fieldContext}. `
      + "Supply a custom snapshotter and a matching equals predicate through "
      + "FormVM options or FormVM.builder().snapshotter(...).equals(...).",
    { cause },
  );
}
