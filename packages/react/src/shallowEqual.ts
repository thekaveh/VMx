/** Object.is plus one-level comparison for arrays and enumerable records. */
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
  const currentRecord = current as Record<string, unknown>;
  const nextRecord = next as Record<string, unknown>;
  const keys = Object.keys(currentRecord);
  if (keys.length !== Object.keys(nextRecord).length) return false;
  return keys.every((key) => Object.hasOwn(nextRecord, key) && Object.is(currentRecord[key], nextRecord[key]));
}
