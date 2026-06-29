/**
 * Lifecycle transition validator.
 *
 * Loads the lifecycle-transitions.json fixture via a static TypeScript JSON
 * import so the data is bundled into the dist by tsup/esbuild at build time.
 * This makes the module browser-safe (no runtime built-in Node module
 * resolution required), and removes the previous fs-search of candidate
 * paths.
 *
 * Public surface:
 *   isLegal(current, operation) → boolean
 *   requireTransition(current, operation) → void (throws StatusTransitionError)
 *   finalState(current, operation) → ConstructionStatus
 */
import { ConstructionStatus } from "./status.js";
import { StatusTransitionError } from "./exceptions.js";
import lifecycleTransitions from "../fixtures/lifecycle-transitions.json" with { type: "json" };

interface TransitionRow {
  from: string;
  via: string;
  to_intermediate: string | null;
  to_final: string | null;
  legal: boolean;
}

interface LifecycleTransitionsFixture {
  transitions: TransitionRow[];
}

const _TABLE: TransitionRow[] = (lifecycleTransitions as LifecycleTransitionsFixture)
  .transitions;

function _statusName(s: ConstructionStatus): string {
  return ConstructionStatus[s];
}

function _findRow(
  current: ConstructionStatus,
  operation: string,
): TransitionRow | undefined {
  const name = _statusName(current);
  return _TABLE.find((r) => r.from === name && r.via === operation);
}

export function isLegal(
  current: ConstructionStatus,
  operation: string,
): boolean {
  const row = _findRow(current, operation);
  return row !== undefined && row.legal;
}

export function requireTransition(
  current: ConstructionStatus,
  operation: string,
): void {
  if (!isLegal(current, operation)) {
    throw new StatusTransitionError(current, operation);
  }
}

export function finalState(
  current: ConstructionStatus,
  operation: string,
): ConstructionStatus {
  const row = _findRow(current, operation);
  if (row === undefined || !row.legal || row.to_final === null) {
    throw new StatusTransitionError(current, operation);
  }
  // VMX-091: validate that the fixture's `to_final` names a real
  // ConstructionStatus member before indexing. Without this guard a fixture
  // typo (e.g. "Constructd") would index to `undefined` typed — unsoundly — as
  // ConstructionStatus and flow on into `_setStatus`. `in` checks membership at
  // runtime so the cast below is sound for a verified forward enum name.
  const key = row.to_final;
  if (!(key in ConstructionStatus)) {
    throw new StatusTransitionError(current, operation);
  }
  return ConstructionStatus[key as keyof typeof ConstructionStatus];
}
