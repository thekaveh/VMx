/**
 * Resolves a splice start index the way `Array.prototype.splice` does:
 * ToIntegerOrInfinity, then negatives count from the end and out-of-range
 * values clamp. Internal; not exported from the package.
 */
export function resolveSpliceStart(start: number, length: number): number {
  const integer = toIntegerOrInfinity(start);
  if (integer < 0) return Math.max(length + integer, 0);
  return Math.min(integer, length);
}

function toIntegerOrInfinity(value: number): number {
  if (Number.isNaN(value) || value === 0) return 0;
  if (!Number.isFinite(value)) return value;
  const integer = Math.trunc(value);
  // Math.trunc(-0.5) is -0; an emitted index must be +0.
  return integer === 0 ? 0 : integer;
}
