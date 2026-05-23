/**
 * Builder validation exception type.
 *
 * Raised by a builder's `build()` method when a required field is missing.
 * Mirrors `BuilderValidationError` in the Python flavor and
 * `BuilderValidationException` in the C# flavor (idiomatic `Error` suffix
 * per ADR-0006).
 *
 * See spec/10-builders.md §Validation.
 */
export class BuilderValidationError extends Error {
  /** Name of the first missing required field that caused the failure. */
  readonly missingField: string;

  constructor(missingField: string, message?: string) {
    super(message ?? `Required field '${missingField}' was not set on the builder.`);
    this.name = "BuilderValidationError";
    this.missingField = missingField;
    // Preserve correct prototype chain across transpilation targets.
    Object.setPrototypeOf(this, new.target.prototype);
  }
}
