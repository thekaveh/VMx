//
// WrapperChangeStream — the `canExecuteChanged` stream a command wrapper owns.
//
// See spec/04-commands.md §8.4 and ADR-0134.
//
// `CompositeCommand`, `DecoratorCommand`, and `ConfirmationDecoratorCommand`
// hold their own subscriptions to the inner change streams and forward them
// through this stream. `close()` releases those subscriptions, notifies once,
// and completes the wrapper's stream, as a disposed `RelayCommand` does. The
// inner streams are never completed; they stay with the inner commands.
//
import Foundation
import Combine

final class WrapperChangeStream {
    private let subject = PassthroughSubject<Void, Never>()
    private let lock = NSLock()
    private var closed = false
    private var subscriptions: [AnyCancellable] = []

    init(forwarding sources: [AnyPublisher<Void, Never>]) {
        var subscriptions: [AnyCancellable] = []
        for source in sources {
            // Capture the stream weakly: an inner command must not keep a
            // discarded wrapper's stream alive.
            subscriptions.append(source.sink { [weak self] _ in self?.forward() })
        }
        lock.lock()
        self.subscriptions = subscriptions
        lock.unlock()
    }

    var publisher: AnyPublisher<Void, Never> {
        subject.eraseToAnyPublisher()
    }

    private func forward() {
        lock.lock()
        let isClosed = closed
        lock.unlock()
        guard !isClosed else { return }
        subject.send(())
    }

    /// Releases the inner subscriptions, notifies once, and completes the
    /// stream. Idempotent. Callbacks run outside the lock.
    func close() {
        lock.lock()
        guard !closed else {
            lock.unlock()
            return
        }
        closed = true
        let released = subscriptions
        subscriptions = []
        lock.unlock()
        released.forEach { $0.cancel() }
        subject.send(())
        subject.send(completion: .finished)
    }
}
