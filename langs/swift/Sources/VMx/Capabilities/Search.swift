//
// Search capability micro-interface — `Searchable` — plus the
// `SearchableState` debounced-predicate helper.
//
// Ports langs/typescript/src/capabilities/search.ts and
// langs/typescript/src/capabilities/searchableState.ts. See
// spec/14-capabilities.md §2.5 and ADR-0014 / ADR-0057.
//
// Swift idiom: bare protocol names (no `I`-prefix), camelCase members.
//
import Combine
import Foundation

/// A VM that exposes a search affordance over its underlying data (CAP-008).
///
/// `searchTerm` is read/write (a concrete VM emits a `PropertyChangedMessage`
/// when it changes, per spec/14 §2.5); `search()` applies the current term.
public protocol Searchable {
    /// The current search term.
    var searchTerm: String { get set }
    /// Whether `search()` may currently be invoked.
    func canSearch() -> Bool
    /// Apply the current `searchTerm`.
    func search()
}

/// Composition-friendly helper implementing `Searchable` over a lazily-read
/// item source and a `(item, term) -> Bool` predicate. Mirrors
/// `searchableState.ts` (ADR-0014).
///
/// `filtered` is recomputed on each *term* change (debounced) and on each
/// explicit `search()` call. It does NOT react to mutations of the underlying
/// source — `items` is read lazily only when the term changes or `search()` is
/// called, so after mutating the source while the term is unchanged callers
/// MUST call `search()` to refresh the view. (This differs from a paged
/// composition, which observes its source.)
public final class SearchableState<T>: Searchable {
    private let itemsProvider: () -> [T]
    private let predicate: (T, String) -> Bool
    private let termSubject = CurrentValueSubject<String, Never>("")
    private let filteredSubject: CurrentValueSubject<[T], Never>
    private let forceSearchSubject = PassthroughSubject<Void, Never>()
    private var subscription: AnyCancellable?
    private var disposed = false

    /// - Parameters:
    ///   - items: lazily-read source of items (re-read on each recompute).
    ///   - predicate: returns `true` when an item matches the given term.
    ///   - debounce: delay applied to term-change recomputes (default 1s);
    ///     `search()` recomputes immediately, bypassing the debounce.
    ///   - scheduler: scheduler the debounce runs on (default `.main`).
    public init(
        items: @escaping () -> [T],
        predicate: @escaping (T, String) -> Bool,
        debounce: DispatchQueue.SchedulerTimeType.Stride = .seconds(1),
        scheduler: DispatchQueue = .main
    ) {
        self.itemsProvider = items
        self.predicate = predicate
        self.filteredSubject = CurrentValueSubject(items().filter { predicate($0, "") })

        let debouncedTerm = termSubject
            .debounce(for: debounce, scheduler: scheduler)
            .eraseToAnyPublisher()
        let forcedTerm = forceSearchSubject
            .map { [weak self] _ in self?.termSubject.value ?? "" }
            .eraseToAnyPublisher()

        self.subscription = Publishers.Merge(debouncedTerm, forcedTerm)
            .sink { [weak self] term in
                guard let self, !self.disposed else { return }
                self.filteredSubject.send(self.applyFilter(term))
            }
    }

    /// The current search term. Reads empty once disposed — parity with
    /// C#/Python/TypeScript, whose getters return "" after dispose rather than the
    /// frozen last value (Combine's `CurrentValueSubject.value` retains it).
    public var searchTerm: String {
        get {
            guard !disposed else { return "" }
            return termSubject.value
        }
        set {
            // Inert once disposed (parity with the other flavors' guarded setters).
            guard !disposed else { return }
            // Spec wording is "emission on a new value" — guard against no-op
            // re-sets so the debounce + recompute don't fire when unchanged.
            guard newValue != termSubject.value else { return }
            termSubject.send(newValue)
        }
    }

    /// The current filtered view, recomputed on each debounced term change and
    /// on each explicit `search()`. Completes on `dispose()`.
    public var filtered: AnyPublisher<[T], Never> {
        filteredSubject.eraseToAnyPublisher()
    }

    /// `true` while the source is non-empty.
    public func canSearch() -> Bool {
        !itemsProvider().isEmpty
    }

    /// Force an immediate recompute against the current term (bypasses debounce).
    public func search() {
        guard !disposed else { return }
        forceSearchSubject.send(())
    }

    private func applyFilter(_ term: String) -> [T] {
        itemsProvider().filter { predicate($0, term) }
    }

    /// Complete `filtered` and halt further notifications. Idempotent.
    public func dispose() {
        guard !disposed else { return }
        disposed = true
        subscription?.cancel()
        subscription = nil
        termSubject.send(completion: .finished)
        filteredSubject.send(completion: .finished)
        forceSearchSubject.send(completion: .finished)
    }
}
