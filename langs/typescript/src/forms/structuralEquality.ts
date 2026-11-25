/**
 * Structural equality for FormVM (internal).
 *
 * `deepEquals` is the default dirty-tracking predicate of FormVM (ADR-0113,
 * ADR-0135, ADR-0152, ADR-0253). Nothing here is part of the public API; the package
 * index does not export this module.
 */

// The error kinds structured cloning keeps. It rebuilds an error from its
// `name`, and any other name (a custom subclass, `AggregateError`) comes back
// as a plain `Error`.
const CLONEABLE_ERROR_NAMES: ReadonlySet<string> = new Set([
  "Error",
  "EvalError",
  "RangeError",
  "ReferenceError",
  "SyntaxError",
  "TypeError",
  "URIError",
]);

function errorKind(error: Error): string {
  // Cloning reads `name` as it is, so a non-string name is not a kept kind. An
  // inherited accessor can throw, as on a forged DOMException; that is no kind.
  let name: unknown;
  try {
    name = error.name;
  } catch {
    return "Error";
  }
  return typeof name === "string" && CLONEABLE_ERROR_NAMES.has(name) ? name : "Error";
}

/**
 * An own data property of an error, as structured cloning reads it. Inherited
 * values and accessors are not cloned, so they compare as absent.
 */
function ownErrorValue(error: Error, key: "message" | "cause"): { value: unknown } | undefined {
  const descriptor = Object.getOwnPropertyDescriptor(error, key);
  return descriptor !== undefined && "value" in descriptor
    ? { value: descriptor.value }
    : undefined;
}

function errorMessage(error: Error): string | undefined {
  const message = ownErrorValue(error, "message");
  return message === undefined ? undefined : String(message.value);
}

// A DOMException clones as a DOMException with its `name` and `message`, which
// it reads through prototype accessors. Its `cause`, custom properties, and
// subclass are dropped.

/** The cloned parts of a genuine DOMException; undefined for any other value. */
function domExceptionParts(error: Error): { name: unknown; message: unknown } | undefined {
  if (typeof DOMException === "undefined" || !(error instanceof DOMException)) return undefined;
  try {
    // The base accessors read the internal slots, so a subclass override is
    // ignored, and they throw for a value that only inherits the prototype.
    return {
      name: Reflect.get(DOMException.prototype, "name", error),
      message: Reflect.get(DOMException.prototype, "message", error),
    };
  } catch {
    return undefined;
  }
}

function isBuffer(value: object): value is ArrayBuffer | SharedArrayBuffer {
  return value instanceof ArrayBuffer
    || (typeof SharedArrayBuffer !== "undefined" && value instanceof SharedArrayBuffer);
}

function sameBinaryConstructor(a: object, b: object): boolean {
  return Object.getPrototypeOf(a) === Object.getPrototypeOf(b);
}

function equalBytes(
  a: ArrayBufferLike,
  aOffset: number,
  b: ArrayBufferLike,
  bOffset: number,
  byteLength: number,
): boolean {
  const aBytes = new Uint8Array(a, aOffset, byteLength);
  const bBytes = new Uint8Array(b, bOffset, byteLength);
  for (let index = 0; index < byteLength; index += 1) {
    if (aBytes[index] !== bBytes[index]) return false;
  }
  return true;
}

/** Compares two boxed primitives with the primitive rules of {@link deepEquals}. */
function boxedValuesEqual(a: { valueOf(): unknown }, b: { valueOf(): unknown }): boolean {
  const x = a.valueOf();
  const y = b.valueOf();
  return x === y || (x !== x && y !== y);
}

// A Blob, File, or CryptoKey clones as a value of the same kind, except that a
// clone may degrade a File to a Blob (Node 20.5 and 22; ADR-0253 §2.1). These
// values have no own enumerable keys, so the plain-object fallback would call
// any two of them equal. They are compared by the state the clone keeps. The
// bytes of a Blob and the key material of a CryptoKey are not compared, because
// reading them is asynchronous (ADR-0253).

type ClonedKind = "File" | "Blob" | "CryptoKey";

/**
 * A File against a Blob: the one mixed pair. A degraded File clone produces it,
 * and a user's replacement of a File with a Blob, or of a Blob with a File,
 * produces it on every runtime (ADR-0253 §2.1).
 */
function isFileAndBlob(a: ClonedKind, b: ClonedKind): boolean {
  return (a === "File" && b === "Blob") || (a === "Blob" && b === "File");
}

/** The kind a structured clone keeps for a value, or undefined for any other value. */
function clonedKind(value: object): ClonedKind | undefined {
  // A File is also a Blob, so the File test comes first.
  if (typeof File !== "undefined" && value instanceof File) return "File";
  if (typeof Blob !== "undefined" && value instanceof Blob) return "Blob";
  if (typeof CryptoKey !== "undefined" && value instanceof CryptoKey) return "CryptoKey";
  return undefined;
}

/**
 * The state a clone of a Blob, File, or CryptoKey keeps, read through the base
 * prototype accessors as the clone reads it. Undefined when an accessor throws,
 * as it does for a value that only inherits the prototype.
 */
function clonedState(value: object, kind: ClonedKind): unknown[] | undefined {
  try {
    if (kind === "CryptoKey") {
      return [
        Reflect.get(CryptoKey.prototype, "type", value),
        Reflect.get(CryptoKey.prototype, "extractable", value),
        Reflect.get(CryptoKey.prototype, "algorithm", value),
        Reflect.get(CryptoKey.prototype, "usages", value),
      ];
    }
    const state: unknown[] = [
      Reflect.get(Blob.prototype, "size", value),
      Reflect.get(Blob.prototype, "type", value),
    ];
    if (kind === "File") {
      state.push(
        Reflect.get(File.prototype, "name", value),
        Reflect.get(File.prototype, "lastModified", value),
      );
    }
    return state;
  } catch {
    return undefined;
  }
}

/**
 * Structural deep-equality used by {@link FormVM.isDirty} when no custom
 * `equals` is supplied. It mirrors the depth the default `structuredClone`
 * snapshotter clones, so comparison and snapshotting stay internally
 * consistent. Unlike the previous `JSON.stringify` comparison it:
 *
 * - never throws on `BigInt` (compared with `===`) or circular references
 *   (guarded with a visited-pair set);
 * - compares `Date` by instant, `Map`/`Set` by contents, `RegExp` by
 *   source/flags, binary buffers/views by constructor and bytes, and arrays and
 *   plain objects by value;
 * - compares `Error` values by what `structuredClone` keeps: the error kind
 *   (the standard error named by `name`, otherwise `Error`), the own
 *   `message`, and the own `cause`, compared recursively. The stack, custom
 *   properties, and subclass identity are not kept by the clone, so they are
 *   not compared;
 * - compares `Blob`, `File`, and `CryptoKey` by the kind and state the clone
 *   keeps: a `Blob`'s size and type, a `File`'s name and lastModified as well,
 *   and a `CryptoKey`'s type, extractable flag, algorithm, and usages. Their
 *   bytes and key material are not compared (ADR-0253). A `File` against a
 *   `Blob` compares by size and type only, a pairing that a clone degrading a
 *   `File` produces and that a user's replacement produces on every runtime
 *   (ADR-0253 §2.1); any other two kinds are unequal;
 * - distinguishes an `undefined`-valued key from a missing key (as
 *   `structuredClone` preserves it);
 * - treats `NaN` as equal to `NaN` (and `+0`/`-0` as equal) for dirty-tracking.
 *
 * Map/Set membership uses SameValueZero (the engine's native `has`), so
 * object-typed Map keys / Set members are compared by reference — adequate for
 * the primitive-keyed models dirty-tracking targets.
 */
export function deepEquals(
  a: unknown,
  b: unknown,
  seen?: Map<unknown, Set<unknown>>,
): boolean {
  // Identity / primitive fast path (also makes +0 === -0 → equal).
  if (a === b) return true;

  // NaN: treat NaN as equal to NaN; any other number pair already failed `===`.
  if (typeof a === "number" && typeof b === "number") {
    return a !== a && b !== b;
  }

  // Anything non-object (incl. bigint, mismatched primitive types, null) that
  // did not pass `===` above is unequal. BigInt's only equal path is `===`.
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) {
    return false;
  }

  // Circular-reference guard: if this exact (a, b) pair is already in flight we
  // treat it as equal — any real difference surfaces on a finite branch first.
  const visited = seen ?? new Map<unknown, Set<unknown>>();
  const partners = visited.get(a);
  if (partners) {
    if (partners.has(b)) return true;
    partners.add(b);
  } else {
    visited.set(a, new Set([b]));
  }

  if (a instanceof Date || b instanceof Date) {
    if (!(a instanceof Date) || !(b instanceof Date)) return false;
    // Compare by instant; an invalid Date (NaN time) equals another invalid
    // Date, as structuredClone preserves it.
    const aTime = a.getTime();
    const bTime = b.getTime();
    return aTime === bTime || (aTime !== aTime && bTime !== bTime);
  }

  // Boxed primitives keep their value through structuredClone, so compare it
  // with the same rules as primitives: NaN equals NaN, and +0 equals -0.
  // Each constructor is checked directly: V8 does not specialize
  // `instanceof` against a loop variable, which doubled the cost (#767).
  if (a instanceof Number || b instanceof Number) {
    return a instanceof Number && b instanceof Number && boxedValuesEqual(a, b);
  }
  if (a instanceof Boolean || b instanceof Boolean) {
    return a instanceof Boolean && b instanceof Boolean && boxedValuesEqual(a, b);
  }
  if (a instanceof String || b instanceof String) {
    return a instanceof String && b instanceof String && boxedValuesEqual(a, b);
  }
  if (a instanceof BigInt || b instanceof BigInt) {
    return a instanceof BigInt && b instanceof BigInt && boxedValuesEqual(a, b);
  }

  if (a instanceof RegExp || b instanceof RegExp) {
    return (
      a instanceof RegExp &&
      b instanceof RegExp &&
      a.source === b.source &&
      a.flags === b.flags
    );
  }

  if (a instanceof Error || b instanceof Error) {
    if (!(a instanceof Error) || !(b instanceof Error)) return false;
    const aDom = domExceptionParts(a);
    const bDom = domExceptionParts(b);
    if (aDom !== undefined || bDom !== undefined) {
      return aDom !== undefined
        && bDom !== undefined
        && aDom.name === bDom.name
        && aDom.message === bDom.message;
    }
    if (errorKind(a) !== errorKind(b) || errorMessage(a) !== errorMessage(b)) return false;
    const aCause = ownErrorValue(a, "cause");
    const bCause = ownErrorValue(b, "cause");
    if (aCause === undefined || bCause === undefined) return aCause === bCause;
    return deepEquals(aCause.value, bCause.value, visited);
  }

  const aIsBuffer = isBuffer(a);
  const bIsBuffer = isBuffer(b);
  if (aIsBuffer || bIsBuffer) {
    return aIsBuffer
      && bIsBuffer
      && sameBinaryConstructor(a, b)
      && a.byteLength === b.byteLength
      && equalBytes(a, 0, b, 0, a.byteLength);
  }

  const aIsView = ArrayBuffer.isView(a);
  const bIsView = ArrayBuffer.isView(b);
  if (aIsView || bIsView) {
    return aIsView
      && bIsView
      && sameBinaryConstructor(a, b)
      && a.byteLength === b.byteLength
      && equalBytes(a.buffer, a.byteOffset, b.buffer, b.byteOffset, a.byteLength);
  }

  const aIsArray = Array.isArray(a);
  const bIsArray = Array.isArray(b);
  if (aIsArray || bIsArray) {
    if (!aIsArray || !bIsArray || a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
      if (!deepEquals(a[i], b[i], visited)) return false;
    }
    return true;
  }

  if (a instanceof Map || b instanceof Map) {
    if (!(a instanceof Map) || !(b instanceof Map) || a.size !== b.size) return false;
    for (const [k, v] of a) {
      if (!b.has(k) || !deepEquals(v, b.get(k), visited)) return false;
    }
    return true;
  }

  if (a instanceof Set || b instanceof Set) {
    if (!(a instanceof Set) || !(b instanceof Set) || a.size !== b.size) return false;
    for (const v of a) {
      if (!b.has(v)) return false;
    }
    return true;
  }

  // A Blob, File, or CryptoKey is compared with a value of its own kind by the
  // state its clone keeps. A File is also compared with a Blob by the Blob state
  // (size and type), in either direction: a degraded File clone produces the
  // pairing, and a user's replacement produces it on every runtime (ADR-0253 §2.1).
  // Any other mixed pair is unequal, and so is a value of these kinds against a
  // plain value.
  const aKind = clonedKind(a);
  const bKind = clonedKind(b);
  if (aKind !== undefined || bKind !== undefined) {
    if (aKind === undefined || bKind === undefined) return false;
    let kind: ClonedKind = aKind;
    if (aKind !== bKind) {
      if (!isFileAndBlob(aKind, bKind)) return false;
      kind = "Blob";
    }
    const aState = clonedState(a, kind);
    const bState = clonedState(b, kind);
    return aState !== undefined
      && bState !== undefined
      && deepEquals(aState, bState, visited);
  }

  // Plain objects: own enumerable string keys, including undefined-valued keys.
  const aObj = a as Record<string, unknown>;
  const bObj = b as Record<string, unknown>;
  const aKeys = Object.keys(aObj);
  const bKeys = Object.keys(bObj);
  if (aKeys.length !== bKeys.length) return false;
  for (const key of aKeys) {
    if (!Object.prototype.hasOwnProperty.call(bObj, key)) return false;
    if (!deepEquals(aObj[key], bObj[key], visited)) return false;
  }
  return true;
}
