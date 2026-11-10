/**
 * Reads an item the way `Array.prototype.at` does: ToIntegerOrInfinity, then
 * a negative index counts from the end. An index outside the array returns
 * `undefined`. The library `lib` setting does not declare
 * `Array.prototype.at`, so the index is resolved here (#1322, ADR-0009 §2.23).
 * Internal; not exported from the package.
 */
export function itemAt<T>(items: readonly T[], index: number): T | undefined {
  const integer = Number.isNaN(index) ? 0 : Math.trunc(index);
  const resolved = integer < 0 ? items.length + integer : integer;
  return resolved >= 0 && resolved < items.length ? items[resolved] : undefined;
}
