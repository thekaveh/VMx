// Filter capability contract. See spec/14-capabilities.md §Filterable and ADR-0022.

/** IFilterable<T> capability: the implementer accepts a typed predicate and exposes a filter decision (CAP-021, ADR-0022). */
export interface IFilterable<T> {
  /** The current filter predicate; null means no filter is applied. */
  filter: ((item: T) => boolean) | null;
  /** Returns true when filtering is currently allowed. */
  canFilter(): boolean;
}
