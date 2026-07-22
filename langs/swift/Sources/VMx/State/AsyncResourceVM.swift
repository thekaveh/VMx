//
// AsyncResourceVM — one cancellable asynchronously acquired presentation value.
//
// See spec/23-async-resource-vm.md and ADR-0100.
//
import Combine
import Foundation

public enum AsyncResourceStatus: String, Sendable {
    case idle = "Idle"
    case loading = "Loading"
    case ready = "Ready"
    case error = "Error"
}

public enum AsyncResourceRetention: String, Sendable {
    case discardPrevious = "DiscardPrevious"
    case retainPrevious = "RetainPrevious"
}

public enum AsyncResourceState<Value> {
    case idle
    case loading(previous: Value?)
    case ready(Value)
    case error(previous: Value?, cause: any Error)

    public var status: AsyncResourceStatus {
        switch self {
        case .idle: .idle
        case .loading: .loading
        case .ready: .ready
        case .error: .error
        }
    }

    public var value: Value? {
        switch self {
        case .idle: nil
        case let .loading(previous): previous
        case let .ready(value): value
        case let .error(previous, _): previous
        }
    }

    public var error: (any Error)? {
        guard case let .error(_, cause) = self else { return nil }
        return cause
    }
}

private enum StableAsyncResourceState<Value> {
    case idle
    case ready(Value)
    case error(previous: Value?, cause: any Error)

    var value: Value? {
        switch self {
        case .idle: nil
        case let .ready(value): value
        case let .error(previous, _): previous
        }
    }

    var publicState: AsyncResourceState<Value> {
        switch self {
        case .idle: .idle
        case let .ready(value): .ready(value)
        case let .error(previous, cause): .error(previous: previous, cause: cause)
        }
    }
}

private final class AsyncResourceOperation {
    let id: UInt64
    private let lock = NSLock()
    private var task: Task<Void, Never>?
    private var waiters: [CheckedContinuation<Void, Never>] = []
    private var finished = false

    init(id: UInt64) {
        self.id = id
    }

    func install(_ task: Task<Void, Never>) {
        lock.lock()
        if finished {
            lock.unlock()
            task.cancel()
            return
        }
        self.task = task
        lock.unlock()
    }

    func cancel() {
        lock.lock()
        let task = self.task
        lock.unlock()
        task?.cancel()
        finish()
    }

    func wait() async {
        await withCheckedContinuation { continuation in
            lock.lock()
            if finished {
                lock.unlock()
                continuation.resume()
                return
            }
            waiters.append(continuation)
            lock.unlock()
        }
    }

    func finish() {
        lock.lock()
        guard !finished else {
            lock.unlock()
            return
        }
        finished = true
        task = nil
        let continuations = waiters
        waiters.removeAll()
        lock.unlock()
        continuations.forEach { $0.resume() }
    }
}

public final class AsyncResourceVM<Value>: ComponentVMBase {
    private let loader: () async throws -> Value
    private let retention: AsyncResourceRetention
    private let cleanupValue: ((Value) -> Void)?
    private let resourceLock = NSRecursiveLock()

    private var currentState: AsyncResourceState<Value> = .idle
    private var stableState: StableAsyncResourceState<Value> = .idle
    private var operationID: UInt64 = 0
    private var operation: AsyncResourceOperation?
    private var resourceDisposed = false

    public private(set) var loadCommand: AsyncRelayCommand
    public private(set) var reloadCommand: AsyncRelayCommand
    public private(set) var cancelCommand: RelayCommand

    public init(
        name: String,
        loader: @escaping () async throws -> Value,
        hub: MessageHubProtocol,
        dispatcher: Dispatcher,
        hint: String = "",
        retention: AsyncResourceRetention = .discardPrevious,
        cleanupValue: ((Value) -> Void)? = nil
    ) {
        self.loader = loader
        self.retention = retention
        self.cleanupValue = cleanupValue
        self.loadCommand = AsyncRelayCommand(
            body: nil, predicate: { false }, triggers: [], throwOnCancel: false
        )
        self.reloadCommand = AsyncRelayCommand(
            body: nil, predicate: { false }, triggers: [], throwOnCancel: false
        )
        self.cancelCommand = RelayCommand(task: nil, predicate: { false }, triggers: [])
        super.init(name: name, hint: hint, hub: hub, dispatcher: dispatcher)

        loadCommand = AsyncRelayCommand(
            body: { [weak self] in await self?.load() },
            predicate: { [weak self] in self?.canLoad() ?? false },
            triggers: [],
            throwOnCancel: false
        )
        reloadCommand = AsyncRelayCommand(
            body: { [weak self] in await self?.reload() },
            predicate: { [weak self] in self?.canReload() ?? false },
            triggers: [],
            throwOnCancel: false
        )
        cancelCommand = RelayCommand(
            task: { [weak self] in self?.cancel() },
            predicate: { [weak self] in self?.canCancel() ?? false },
            triggers: []
        )
    }

    public override var type: ViewModelType { .component }

    public var state: AsyncResourceState<Value> {
        resourceLock.lock()
        defer { resourceLock.unlock() }
        return currentState
    }

    public func load() async {
        guard let admitted = admit(reload: false) else { return }
        await waitForOperation(admitted)
    }

    public func reload() async {
        guard let admitted = admit(reload: true) else { return }
        await waitForOperation(admitted)
    }

    public func cancel() {
        resourceLock.lock()
        let current = operation
        resourceLock.unlock()
        guard let current else { return }

        loadCommand.cancel()
        reloadCommand.cancel()
        cancelOperation(current.id)
    }

    public override func _onDispose() {
        resourceLock.lock()
        guard !resourceDisposed else {
            resourceLock.unlock()
            return
        }
        resourceDisposed = true
        operationID &+= 1
        let active = operation
        operation = nil
        let accepted = stableState.value
        stableState = .idle
        resourceLock.unlock()

        active?.cancel()
        loadCommand.dispose()
        reloadCommand.dispose()
        cancelCommand.dispose()
        accepted.map(cleanup)
    }

    private func canLoad() -> Bool {
        resourceLock.lock()
        defer { resourceLock.unlock() }
        return !resourceDisposed && currentState.status == .idle
    }

    private func canReload() -> Bool {
        resourceLock.lock()
        defer { resourceLock.unlock() }
        return !resourceDisposed && currentState.status != .idle
    }

    private func canCancel() -> Bool {
        resourceLock.lock()
        defer { resourceLock.unlock() }
        return !resourceDisposed && currentState.status == .loading
    }

    private func admit(reload: Bool) -> AsyncResourceOperation? {
        resourceLock.lock()
        let allowed = !resourceDisposed && (reload
            ? currentState.status != .idle
            : currentState.status == .idle)
        guard allowed else {
            resourceLock.unlock()
            return nil
        }

        operationID &+= 1
        let admitted = AsyncResourceOperation(id: operationID)
        let superseded = operation
        operation = admitted

        var discarded: Value?
        if retention == .discardPrevious {
            discarded = stableState.value
            stableState = .idle
        }
        let previous = retention == .retainPrevious ? stableState.value : nil
        currentState = .loading(previous: previous)
        resourceLock.unlock()

        superseded?.cancel()
        discarded.map(cleanup)

        resourceLock.lock()
        let shouldNotify = !resourceDisposed
            && operation?.id == admitted.id
            && operationID == admitted.id
        resourceLock.unlock()
        guard shouldNotify else {
            admitted.finish()
            return admitted
        }
        notifyStateChanged()

        resourceLock.lock()
        let shouldStart = !resourceDisposed
            && operation?.id == admitted.id
            && operationID == admitted.id
        resourceLock.unlock()
        guard shouldStart else {
            admitted.finish()
            return admitted
        }

        let loader = self.loader
        let cleanupLate = self.cleanupValue
        let owner = UncheckedSendableWeakBox(self)
        let context = UncheckedSendableBox((admitted, loader, cleanupLate))
        let task = Task { [owner, context] in
            let (admitted, loader, cleanupLate) = context.value
            do {
                let value = try await loader()
                if let owner = owner.value {
                    owner.completeSuccess(value, operation: admitted)
                } else {
                    cleanupLate?(value)
                }
            } catch is CancellationError {
                owner.value?.completeCancellation(operation: admitted)
            } catch {
                owner.value?.completeFailure(error, operation: admitted)
            }
            admitted.finish()
        }
        admitted.install(task)
        return admitted
    }

    private func waitForOperation(_ admitted: AsyncResourceOperation) async {
        let owner = UncheckedSendableWeakBox(self)
        let operationID = admitted.id
        await withTaskCancellationHandler {
            await admitted.wait()
        } onCancel: { [owner, operationID] in
            owner.value?.cancelOperation(operationID)
        }
    }

    private func cancelOperation(_ id: UInt64) {
        resourceLock.lock()
        guard let active = operation, active.id == id else {
            resourceLock.unlock()
            return
        }
        operationID &+= 1
        operation = nil
        currentState = stableState.publicState
        resourceLock.unlock()

        active.cancel()
        notifyStateChanged()
    }

    private func completeCancellation(operation admitted: AsyncResourceOperation) {
        cancelOperation(admitted.id)
    }

    private func completeSuccess(_ value: Value, operation admitted: AsyncResourceOperation) {
        resourceLock.lock()
        guard !resourceDisposed,
              operation?.id == admitted.id,
              operationID == admitted.id else {
            resourceLock.unlock()
            cleanup(value)
            return
        }
        let replaced = stableState.value
        operation = nil
        stableState = .ready(value)
        currentState = .ready(value)
        let committedID = operationID
        resourceLock.unlock()

        replaced.map(cleanup)
        resourceLock.lock()
        let shouldNotify = !resourceDisposed
            && operationID == committedID
            && operation == nil
        resourceLock.unlock()
        if shouldNotify { notifyStateChanged() }
    }

    private func completeFailure(_ error: any Error, operation admitted: AsyncResourceOperation) {
        resourceLock.lock()
        guard !resourceDisposed,
              operation?.id == admitted.id,
              operationID == admitted.id else {
            resourceLock.unlock()
            return
        }
        let previous = stableState.value
        operation = nil
        stableState = .error(previous: previous, cause: error)
        currentState = .error(previous: previous, cause: error)
        resourceLock.unlock()
        notifyStateChanged()
    }

    private func cleanup(_ value: Value) {
        cleanupValue?(value)
    }

    private func notifyStateChanged() {
        _notifyPropertyChanged("state")
        loadCommand.raiseCanExecuteChanged()
        reloadCommand.raiseCanExecuteChanged()
        cancelCommand.raiseCanExecuteChanged()
    }
}
