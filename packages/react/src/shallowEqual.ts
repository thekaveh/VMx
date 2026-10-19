/** Object.is plus one-level comparison for arrays and plain enumerable records. */
export function shallowEqual(current: unknown, next: unknown): boolean {
  if (Object.is(current, next)) return true;
  const currentIsArray = Array.isArray(current);
  const nextIsArray = Array.isArray(next);
  if (currentIsArray !== nextIsArray) return false;
  if (currentIsArray && nextIsArray) {
    if (current.length !== next.length) return false;
    return current.every((value, index) => Object.is(value, next[index]));
  }
  if (
    typeof current !== "object" || current === null ||
    typeof next !== "object" || next === null
  ) return false;
  // Only plain records compare by keys. A Date, Map, Set, or class instance
  // has no meaningful own enumerable keys, so it compares by identity.
  if (!isPlainObject(current) || !isPlainObject(next)) return false;
  const currentRecord = current as Record<string, unknown>;
  const nextRecord = next as Record<string, unknown>;
  const keys = Object.keys(currentRecord);
  if (keys.length !== Object.keys(nextRecord).length) return false;
  return keys.every((key) => Object.hasOwn(nextRecord, key) && Object.is(currentRecord[key], nextRecord[key]));
}

function isPlainObject(value: object): boolean {
  const prototype: unknown = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}
