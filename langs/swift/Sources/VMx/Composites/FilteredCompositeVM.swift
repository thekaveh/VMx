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

    public var visible: [Child] { visibleStorage }
    public var visibleCount: Int { visibleStorage.count }
    public var current: Child?

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
        self.predicate = predicate
        recompute()
    }

    public func setCurrent(_ item: Child?) {
        if let item, !visibleStorage.contains(where: { $0 === item }) {
            preconditionFailure("current must be nil or a visible item")
        }
        if current === item { return }
        current = item
        changedSubject.send(())
    }

    public func moveToNextVisible() {
        guard !visibleStorage.isEmpty else {
            setCurrent(nil)
            return
        }
        guard let current, let index = visibleStorage.firstIndex(where: { $0 === current }) else {
            setCurrent(visibleStorage[0])
            return
        }
        setCurrent(visibleStorage[min(index + 1, visibleStorage.count - 1)])
    }

    public func moveToPreviousVisible() {
        guard !visibleStorage.isEmpty else {
            setCurrent(nil)
            return
        }
        guard let current, let index = visibleStorage.firstIndex(where: { $0 === current }) else {
            setCurrent(visibleStorage[0])
            return
        }
        setCurrent(visibleStorage[max(index - 1, 0)])
    }

    open func orderedVisible() -> [Child] {
        (0..<source.count).map { source.at($0) }.filter(predicate)
    }

    func recompute() {
        visibleStorage = orderedVisible()
        if let current, !visibleStorage.contains(where: { $0 === current }) {
            self.current = cursorPolicy == .snapToFirst ? visibleStorage.first : nil
        } else if current == nil && cursorPolicy == .snapToFirst {
            current = visibleStorage.first
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
