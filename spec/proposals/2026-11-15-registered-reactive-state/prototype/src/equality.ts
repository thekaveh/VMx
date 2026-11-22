/**
 * Equalities: `Object.is` is the default of every node (R3.1, R3.2).
 *
 * A node's equality is user code. The graph calls it through `compareValues` (graph.ts), which gives it a defined
 * context (fix round 2, R6.10).
 */

/** Equality of two values of one node. */
export type Equality<T> = (a: T, b: T) => boolean;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null) return false;
  const proto: unknown = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

/**
 * `Object.is`; or two arrays of equal length whose items are `Object.is`-equal; or two plain objects (prototype
 * `Object.prototype` or `null`) with the same own enumerable keys whose values are `Object.is`-equal.
 */
export function shallowEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i += 1) {
      if (!Object.is(a[i], b[i])) return false;
    }
    return true;
  }
  if (isPlainObject(a) && isPlainObject(b)) {
    const keysA = Object.keys(a);
    const keysB = Object.keys(b);
    if (keysA.length !== keysB.length) return false;
    for (const key of keysA) {
      if (!Object.prototype.hasOwnProperty.call(b, key)) return false;
      if (!Object.is(a[key], b[key])) return false;
    }
    return true;
  }
  return false;
}

/** Options of {@link structurallyEqual}. */
export interface StructuralOptions {
  /** The result for a pair that the comparison reaches at its depth limit (32 levels). Default false. */
  readonly atLimit?: boolean;
}

const DEPTH_LIMIT = 32;

/**
 * Deep structural equality for the development diagnostics (R19.1 staleness check, R19.8 keyed reloads). Two objects
 * must have the same prototype. Arrays compare item by item; `Map` by keys (identity) and values; `Set` by members
 * (identity); `Date` by time; `RegExp` by source and flags; plain objects and class instances by their own enumerable
 * string keys.
 *
 * Fix round 2 (R19.1):
 * - Functions compare by their source text, so a fresh closure that a computed builds from tracked state (the `run`
 *   of a menu entry) is equal to the closure it replaces (MM1).
 * - The comparison is co-inductive: a pair of objects already being compared counts as equal, so an object graph
 *   with back references (a parent link) terminates and compares by structure (MM2).
 * - At the depth limit the result is `options.atLimit`. The staleness check passes true: it reports nothing when it
 *   cannot decide.
 */
export function structurallyEqual(a: unknown, b: unknown, options: StructuralOptions = {}): boolean {
  return compareDeep(a, b, 0, new Map(), options.atLimit === true);
}

function sourceOf(fn: unknown): string {
  try {
    return Function.prototype.toString.call(fn);
  } catch {
    return "";
  }
}

function compareDeep(
  a: unknown,
  b: unknown,
  depth: number,
  inProgress: Map<object, Set<object>>,
  atLimit: boolean,
): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a === "function" && typeof b === "function") return sourceOf(a) === sourceOf(b);
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Object.getPrototypeOf(a) !== Object.getPrototypeOf(b)) return false;
  if (depth >= DEPTH_LIMIT) return atLimit;
  let partners = inProgress.get(a);
  if (partners?.has(b) === true) return true;
  if (partners === undefined) {
    partners = new Set();
    inProgress.set(a, partners);
  }
  partners.add(b);
  const next = depth + 1;
  if (Array.isArray(a)) {
    const other = b as readonly unknown[];
    if (a.length !== other.length) return false;
    for (let i = 0; i < a.length; i += 1) {
      if (!compareDeep(a[i], other[i], next, inProgress, atLimit)) return false;
    }
    return true;
  }
  if (a instanceof Date) return a.getTime() === (b as Date).getTime();
  if (a instanceof RegExp) return String(a) === String(b);
  if (a instanceof Map) {
    const other = b as ReadonlyMap<unknown, unknown>;
    if (a.size !== other.size) return false;
    for (const [key, value] of a) {
      if (!other.has(key) || !compareDeep(value, other.get(key), next, inProgress, atLimit)) return false;
    }
    return true;
  }
  if (a instanceof Set) {
    const other = b as ReadonlySet<unknown>;
    if (a.size !== other.size) return false;
    for (const value of a) if (!other.has(value)) return false;
    return true;
  }
  const recordA = a as Record<string, unknown>;
  const recordB = b as Record<string, unknown>;
  const keysA = Object.keys(recordA);
  const keysB = Object.keys(recordB);
  if (keysA.length !== keysB.length) return false;
  for (const key of keysA) {
    if (!Object.prototype.hasOwnProperty.call(recordB, key)) return false;
    if (!compareDeep(recordA[key], recordB[key], next, inProgress, atLimit)) return false;
  }
  return true;
}

/**
 * The equality of two errors of one node (fix round 2, R16): the same value, or two `Error` objects with
 * the same prototype, name and message. A computed that fails with the same message on every evaluation keeps one
 * error state; a computed whose error changes (another message, another class) has changed.
 */
export function errorsEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (!(a instanceof Error) || !(b instanceof Error)) return false;
  return Object.getPrototypeOf(a) === Object.getPrototypeOf(b) && a.name === b.name && a.message === b.message;
}
