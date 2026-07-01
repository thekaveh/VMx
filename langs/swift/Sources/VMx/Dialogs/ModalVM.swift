//
// ModalVM — VM-backed modal result primitive.
//

/// Result-bearing VM-backed modal contract.
public protocol ModalVM: AnyObject {
    associatedtype Result

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
public final class BasicModalVM<Result>: ModalVM {
    public let cancellationResult: Result
    public private(set) var result: Result?
    public private(set) var isDismissed = false

    private var waiters: [CheckedContinuation<Result, Never>] = []

    public init(cancellationResult: Result) {
        self.cancellationResult = cancellationResult
    }

    public func dismiss(_ result: Result) {
        guard !isDismissed else { return }
        self.result = result
        isDismissed = true
        let continuations = waiters
        waiters.removeAll()
        for continuation in continuations {
            continuation.resume(returning: result)
        }
    }

    public func dispose() {
        dismiss(cancellationResult)
    }

    public func waitResult() async -> Result {
        if let result {
            return result
        }
        return await withCheckedContinuation { continuation in
            waiters.append(continuation)
        }
    }
}
