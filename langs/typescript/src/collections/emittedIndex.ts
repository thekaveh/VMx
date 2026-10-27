/**
 * Returns `index` with -0 replaced by +0. `Number.isInteger(-0)` is true and
 * `-0 < 0` is false, so an index guard admits -0; an emitted index must be +0
 * (#769). Internal; not exported from the package.
 */
export function emittedIndex(index: number): number {
  return index === 0 ? 0 : index;
}
