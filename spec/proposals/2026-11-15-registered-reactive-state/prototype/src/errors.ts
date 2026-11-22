/**
 * Errors of the registered reactive state layer (R16).
 */

/** A write, a registration or a lifecycle call inside an evaluation frame (R6.2, R3.3, R16). */
export class ReactiveWriteError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ReactiveWriteError";
  }
}

/** A node read during its own evaluation (R16). */
export class ReactiveCycleError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ReactiveCycleError";
  }
}

/** The development drain bound was exceeded (R9.6). */
export class ReactiveOverflowError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ReactiveOverflowError";
  }
}
