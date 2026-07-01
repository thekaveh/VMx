//
// BindableCollection — Combine → SwiftUI bridge for a snapshot-based collection.
//
// On every `publisher` emission, calls `snapshot()` and republishes the
// result as `@Published var items` on the main run loop, triggering
// SwiftUI list re-renders.
//
import Combine
import SwiftUI

/// Combine → SwiftUI bridge for a VM-backed collection.
///
/// Initialise with any `Void`-emitting publisher (e.g. mapped from a
/// `CompositeVM.collectionChanged` or `propertyChanged` stream) and a closure
/// that produces the current snapshot.
final class BindableCollection<T>: ObservableObject {
    /// Current snapshot. Updated on the main run loop on each publisher emission.
    @Published var items: [T]
    private var cancellable: AnyCancellable?

    init<P: Publisher>(
        publisher: P,
        snapshot: @escaping () -> [T]
    ) where P.Output == Void, P.Failure == Never {
        items = snapshot()
        cancellable = publisher
            .receive(on: RunLoop.main)
            .sink { [weak self] in
                self?.items = snapshot()
            }
    }
}
