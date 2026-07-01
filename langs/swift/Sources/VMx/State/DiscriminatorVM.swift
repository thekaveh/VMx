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

    public func isActive(_ key: Key) -> Bool {
        activeKey == key
    }

    public func setActiveKey(_ key: Key) {
        guard !disposed, key != activeKey else { return }
        activeKey = key
        activeChangedSubject.send(key)
    }

    public func modalOpen(_ modalKey: Key) {
        guard !disposed else { return }
        modalStack.append(activeKey)
        setActiveKey(modalKey)
    }

    public func modalClose() {
        guard !disposed, let previous = modalStack.popLast() else { return }
        setActiveKey(previous)
    }

    public func dispose() {
        guard !disposed else { return }
        disposed = true
        activeChangedSubject.send(completion: .finished)
    }
}
