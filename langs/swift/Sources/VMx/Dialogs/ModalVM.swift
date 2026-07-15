//
// ModalVM — VM-backed modal result primitive.
//

import Foundation

private enum BasicModalState<Result: Sendable> {
    case pending([CheckedContinuation<Result, Never>])
    case dismissed(Result)
}

private enum ModalWaitDisposition<Result: Sendable> {
    case registered
    case resolved(Result)
}

/// Result-bearing VM-backed modal contract.
public protocol ModalVM: AnyObject {
    associatedtype Result: Sendable

    /// Result used when the modal is cancelled or disposed.
    var cancellationResult: Result { get }

    /// Dismissal result, or `nil` before dismissal.
    var result: Result? { get }

    /// `true` after dismissal or disposal.
    var isDismissed: Bool { get }

    /// Complete the modal with `result`. Idempotent.
    func dismiss(_ result: Result)

    /// Cancel the modal with `cancellationResult`. Idempotent.
    func dispose()

    /// Wait for dismissal and return the resolved result.
    func waitResult() async -> Result
}

/// Small base implementation for result-bearing VM-backed modals.
public final class BasicModalVM<Result: Sendable>: ModalVM {
    public let cancellationResult: Result
    private let lock = NSLock()
    private var state: BasicModalState<Result> = .pending([])

    public var result: Result? {
        lock.withLock {
            switch state {
            case .pending:
                nil
            case let .dismissed(result):
                Optional.some(result)
            }
        }
    }

    public var isDismissed: Bool {
        lock.withLock {
            if case .dismissed = state {
                true
            } else {
                false
            }
        }
    }

    public init(cancellationResult: Result) {
        self.cancellationResult = cancellationResult
    }

    public func dismiss(_ result: Result) {
        let continuations: [CheckedContinuation<Result, Never>]? = lock.withLock {
            switch state {
            case let .pending(waiters):
                state = .dismissed(result)
                return waiters
            case .dismissed:
                return nil
            }
        }
        guard let continuations else { return }
        for continuation in continuations {
            continuation.resume(returning: result)
        }
    }

    public func dispose() {
        dismiss(cancellationResult)
    }

    public func waitResult() async -> Result {
        return await withCheckedContinuation { continuation in
            let disposition: ModalWaitDisposition<Result> = lock.withLock {
                switch state {
                case var .pending(waiters):
                    waiters.append(continuation)
                    state = .pending(waiters)
                    return .registered
                case let .dismissed(result):
                    return .resolved(result)
                }
            }
            if case let .resolved(result) = disposition {
                continuation.resume(returning: result)
            }
        }
    }
}
