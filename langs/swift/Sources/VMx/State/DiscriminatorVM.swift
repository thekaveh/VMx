//
// DiscriminatorVM — owns one active key with modal precedence helpers.
//
import Combine

public final class DiscriminatorVM<Key: Equatable> {
    private var activeChangedSubject = PassthroughSubject<Key, Never>()
    private var modalStack: [Key] = []
    private var disposed = false

    public private(set) var activeKey: Key

    public init(initial: Key) {
        self.activeKey = initial
    }

    public var activeChanged: AnyPublisher<Key, Never> {
        activeChangedSubject.eraseToAnyPublisher()
    }

    public var modalDepth: Int {
        modalStack.count
    }

    public func isActive(_ key: Key) -> Bool {
        activeKey == key
    }

    public func setActiveKey(_ key: Key) {
        guard !disposed else { return }
        modalStack.removeAll()
        setActiveKeyPreservingModals(key)
    }

    private func setActiveKeyPreservingModals(_ key: Key) {
        guard key != activeKey else { return }
        activeKey = key
        activeChangedSubject.send(key)
    }

    public func modalOpen(_ modalKey: Key) {
        guard !disposed else { return }
        modalStack.append(activeKey)
        setActiveKeyPreservingModals(modalKey)
    }

    public func modalClose() {
        guard !disposed, let previous = modalStack.popLast() else { return }
        setActiveKeyPreservingModals(previous)
    }

    public func clearModals() {
        guard !disposed else { return }
        modalStack.removeAll()
    }

    public func dispose() {
        guard !disposed else { return }
        disposed = true
        modalStack.removeAll()
        activeChangedSubject.send(completion: .finished)
    }
}
