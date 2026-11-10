//
// FilteredCompositeVM.swift — visible projection over a CompositeVM source.
//
import Combine

public enum FilteredCursorPolicy {
    case snapToFirst
    case clear
    case preserveIfVisible
}

open class FilteredCompositeVM<Child: ComponentVMBase> {
    let source: CompositeVM<Child>
    private var predicate: (Child) -> Bool
    private let cursorPolicy: FilteredCursorPolicy
    private var visibleStorage: [Child] = []
    private var cancellables: Set<AnyCancellable> = []
    private var disposed = false
    private let changedSubject = PassthroughSubject<Void, Never>()
    private var currentStorage: Child?

    public var visible: [Child] { visibleStorage }
    public var visibleCount: Int { visibleStorage.count }
    public var current: Child? {
        get { currentStorage }
        set { setCurrent(newValue) }
    }

    public var changed: AnyPublisher<Void, Never> {
        changedSubject.eraseToAnyPublisher()
    }

    public init(
        _ source: CompositeVM<Child>,
        cursorPolicy: FilteredCursorPolicy = .snapToFirst,
        predicate: @escaping (Child) -> Bool = { _ in true }
    ) {
        self.source = source
        self.cursorPolicy = cursorPolicy
        self.predicate = predicate
        source.collectionChanged
            .sink { [weak self] _ in self?.recompute() }
            .store(in: &cancellables)
        recompute()
    }

    init(
        _ source: CompositeVM<Child>,
        cursorPolicy: FilteredCursorPolicy,
        predicate: @escaping (Child) -> Bool,
        deferInitialRecompute: Bool
    ) {
        self.source = source
        self.cursorPolicy = cursorPolicy
        self.predicate = predicate
        source.collectionChanged
            .sink { [weak self] _ in self?.recompute() }
            .store(in: &cancellables)
        if !deferInitialRecompute { recompute() }
    }

    public func setPredicate(_ predicate: @escaping (Child) -> Bool) {
        // A disposed projection stays frozen (disposal contract, DISP-006).
        guard !disposed else { return }
        self.predicate = predicate
        recompute()
    }

    /// Moves the cursor to `item`, which must be `nil` or a visible item.
    /// Another item is a programmer error and traps, as the `current` setter
    /// does (ADR-0009). `setCurrentResult(_:)` is the catchable form
    /// (ADR-0217).
    public func setCurrent(_ item: Child?) {
        if case let .failure(error) = setCurrentResult(item) {
            preconditionFailure("current must be nil or a visible item: \(error)")
        }
    }

    /// Catchable form of `setCurrent(_:)` (ADR-0217). For a non-`nil` item
    /// that is not visible, it returns a `CompositeMembershipError` failure,
    /// changes nothing and emits nothing on `changed`. C#, Python and
    /// TypeScript `SetCurrent` raise for the same item. A disposed projection
    /// stays frozen and ignores the call.
    @discardableResult
    public func setCurrentResult(_ item: Child?) -> Result<Void, CompositeMembershipError> {
        guard !disposed else { return .success(()) }
        if let item, !visibleStorage.contains(where: { $0 === item }) {
            return .failure(CompositeMembershipError(
                memberName: item.name, compositeName: source.name, reason: .notVisible
            ))
        }
        if currentStorage === item { return .success(()) }
        currentStorage = item
        changedSubject.send(())
        return .success(())
    }

    public func moveToNextVisible() {
        guard !disposed else { return }
        guard !visibleStorage.isEmpty else {
            setCurrent(nil)
            return
        }
        guard let currentStorage, let index = visibleStorage.firstIndex(where: { $0 === currentStorage }) else {
            setCurrent(visibleStorage[0])
            return
        }
        setCurrent(visibleStorage[min(index + 1, visibleStorage.count - 1)])
    }

    public func moveToPreviousVisible() {
        guard !disposed else { return }
        guard !visibleStorage.isEmpty else {
            setCurrent(nil)
            return
        }
        guard let currentStorage, let index = visibleStorage.firstIndex(where: { $0 === currentStorage }) else {
            setCurrent(visibleStorage[0])
            return
        }
        setCurrent(visibleStorage[max(index - 1, 0)])
    }

    open func orderedVisible() -> [Child] {
        (0..<source.count).map { source.at($0) }.filter(predicate)
    }

    func recompute() {
        guard !disposed else { return }
        visibleStorage = orderedVisible()
        if let currentStorage, !visibleStorage.contains(where: { $0 === currentStorage }) {
            self.currentStorage = cursorPolicy == .snapToFirst ? visibleStorage.first : nil
        } else if currentStorage == nil && cursorPolicy == .snapToFirst {
            currentStorage = visibleStorage.first
        }
        changedSubject.send(())
    }

    public func dispose() {
        guard !disposed else { return }
        disposed = true
        cancellables.removeAll()
        changedSubject.send(completion: .finished)
    }
}
