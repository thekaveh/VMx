//
// Builder validation error.
//
// Raised by a builder's `build()` method when a required field is missing.
// Mirrors `BuilderValidationError` (Python) / `BuilderValidationError` (TS)
// / `BuilderValidationException` (C#).
//
// See spec/10-builders.md §Validation.
//
import Foundation

public struct BuilderValidationError: Error, CustomStringConvertible {
    /// Name of the first missing required field.
    public let missingField: String
    private let customMessage: String?

    public init(missingField: String, message: String? = nil) {
        self.missingField = missingField
        self.customMessage = message
    }

    public var description: String {
        customMessage
            ?? "Required field '\(missingField)' was not set on the builder."
    }
}
