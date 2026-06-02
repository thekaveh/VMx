//
// ConstructionStatus — five-state lifecycle enum.
//
// Values match the C# / Python / TypeScript counterparts so that JSON
// fixtures round-trip cleanly across language boundaries.
//
// See spec/02-lifecycle.md for the full state-machine contract.
//
import Foundation

public enum ConstructionStatus: Int, Sendable, CaseIterable {
    /// Terminal state. Once entered, cannot leave.
    case disposed = 0
    /// Transient state during `destruct()`.
    case destructing = 1
    /// Initial state of a freshly built VM.
    case destructed = 2
    /// Transient state during `construct()`.
    case constructing = 3
    /// Ready-to-use state.
    case constructed = 4

    /// Stable string name matching the JSON fixture vocabulary
    /// (`Destructed`, `Constructing`, `Constructed`, `Destructing`,
    /// `Disposed`).
    public var name: String {
        switch self {
        case .disposed: return "Disposed"
        case .destructing: return "Destructing"
        case .destructed: return "Destructed"
        case .constructing: return "Constructing"
        case .constructed: return "Constructed"
        }
    }
}

/// Raised when a lifecycle operation is forbidden from the current state.
///
/// See spec/02-lifecycle.md §Invariants 3 and 5.
public struct StatusTransitionError: Error, CustomStringConvertible {
    public let currentStatus: ConstructionStatus
    public let attemptedOperation: String

    public init(currentStatus: ConstructionStatus, attemptedOperation: String) {
        self.currentStatus = currentStatus
        self.attemptedOperation = attemptedOperation
    }

    public var description: String {
        "Cannot \(attemptedOperation) from state \(currentStatus.name)."
    }
}
