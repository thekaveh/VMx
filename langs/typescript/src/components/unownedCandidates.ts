import type { ComponentVMBase, IOwningParentVM } from "./componentVMBase.js";

/**
 * @internal Disposes the candidates that a failed population built and nobody
 * owns (#1324). A population fails when a later factory or projector throws,
 * or when its preflight refuses it before the commit.
 *
 * A candidate that has a parent, that another ownership transaction holds, or
 * that is an owner on the ancestor chain of `parent`, belongs to someone else
 * and is skipped. Each canonical identity is disposed once. The disposal is
 * best-effort: the population's own failure is the one that propagates.
 *
 * The checks and the disposal run in one synchronous step. Another
 * population can take a candidate only before the checks, and then the
 * checks skip it.
 */
export function disposeUnownedCandidates(
  parent: IOwningParentVM,
  candidates: readonly (ComponentVMBase | null | undefined)[],
): void {
  const seen = new Set<ComponentVMBase>();
  for (const candidate of candidates) {
    if (candidate === null || candidate === undefined) continue;
    const identity = candidate._ownershipIdentity;
    if (seen.has(identity)) continue;
    seen.add(identity);
    if (candidate._parent !== null || identity._ownershipInProgress) continue;
    if (ownsOnChain(parent, identity)) continue;
    try {
      candidate.dispose();
    } catch {
      // Best-effort: the population's own failure propagates.
    }
  }
}

function ownsOnChain(parent: IOwningParentVM, identity: ComponentVMBase): boolean {
  for (let cursor: IOwningParentVM | null = parent; cursor !== null; cursor = cursor.ownerParent) {
    if (cursor.owner._ownershipIdentity === identity) return true;
  }
  return false;
}
