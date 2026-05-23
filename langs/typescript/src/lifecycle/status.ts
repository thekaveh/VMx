/**
 * ConstructionStatus — five-state lifecycle enum.
 *
 * Values match the Python and C# counterparts so that JSON fixtures
 * round-trip cleanly across language boundaries.
 *
 * See spec/02-lifecycle.md for the full state-machine contract.
 */
export enum ConstructionStatus {
  /** Terminal state. Once entered, cannot leave. */
  Disposed = 0,
  /** Transient state during destruct(). */
  Destructing = 1,
  /** Initial state of a freshly built VM. */
  Destructed = 2,
  /** Transient state during construct(). */
  Constructing = 3,
  /** Ready-to-use state. */
  Constructed = 4,
}
