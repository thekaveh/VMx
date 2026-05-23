/**
 * StatusTransitionError — raised when a lifecycle operation is forbidden.
 *
 * See spec/02-lifecycle.md §Invariants 3 and 5.
 */
import { ConstructionStatus } from "./status.js";

export class StatusTransitionError extends Error {
  readonly currentStatus: ConstructionStatus;
  readonly attemptedOperation: string;

  constructor(currentStatus: ConstructionStatus, attemptedOperation: string) {
    super(
      `Cannot ${attemptedOperation} from state ${ConstructionStatus[currentStatus]}.`,
    );
    this.name = "StatusTransitionError";
    this.currentStatus = currentStatus;
    this.attemptedOperation = attemptedOperation;
    // Restore prototype chain in transpiled environments.
    Object.setPrototypeOf(this, new.target.prototype);
  }
}
