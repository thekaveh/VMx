/**
 * True when a required builder field holds no value: `null` or `undefined`.
 *
 * Builders use this in `build()` so that a JavaScript caller or a cast that
 * passes `undefined` is reported as a missing field, the same as `null`.
 * Internal to the package; not exported from `index.ts`.
 */
export function isUnset(value: unknown): value is null | undefined {
  return value === null || value === undefined;
}
