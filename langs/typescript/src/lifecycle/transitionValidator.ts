/**
 * Lifecycle transition validator.
 *
 * Loads spec/fixtures/lifecycle-transitions.json once (lazy) and exposes:
 *   isLegal(current, operation) → boolean
 *   require(current, operation) → void (throws StatusTransitionError if illegal)
 *   finalState(current, operation) → ConstructionStatus
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { ConstructionStatus } from "./status.js";
import { StatusTransitionError } from "./exceptions.js";

interface TransitionRow {
  from: string;
  via: string;
  to_intermediate: string | null;
  to_final: string | null;
  legal: boolean;
}

const _FIXTURE_NAME = "lifecycle-transitions.json";

function _loadTable(): TransitionRow[] {
  // Locate src/fixtures/ relative to this compiled module's directory.
  const here = dirname(fileURLToPath(import.meta.url));
  // At runtime: dist/ → src/fixtures is two levels up + src/fixtures.
  // At test time (Vitest): src/lifecycle/ → ../fixtures.
  const candidates = [
    join(here, "..", "fixtures", _FIXTURE_NAME),
    join(here, "..", "..", "src", "fixtures", _FIXTURE_NAME),
    join(here, "..", "..", "..", "spec", "fixtures", _FIXTURE_NAME),
  ];
  for (const candidate of candidates) {
    try {
      const raw = readFileSync(candidate, "utf-8");
      // JSON.parse returns `unknown`; cast to the known fixture shape.
      const parsed: unknown = JSON.parse(raw);
      const data = parsed as { transitions: TransitionRow[] };
      return data.transitions;
    } catch {
      // try next candidate
    }
  }
  throw new Error(
    `Cannot locate ${_FIXTURE_NAME}. Run 'npm run sync-fixtures' first.`,
  );
}

let _table: TransitionRow[] | null = null;

function _getTable(): TransitionRow[] {
  if (_table === null) {
    _table = _loadTable();
  }
  return _table;
}

function _statusName(s: ConstructionStatus): string {
  return ConstructionStatus[s];
}

function _findRow(
  current: ConstructionStatus,
  operation: string,
): TransitionRow | undefined {
  const name = _statusName(current);
  return _getTable().find((r) => r.from === name && r.via === operation);
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
  const key = row.to_final as keyof typeof ConstructionStatus;
  return ConstructionStatus[key];
}
