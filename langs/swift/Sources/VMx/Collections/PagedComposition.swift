//
// PagedComposition.swift — paged view over a source array.
//
// Implements Pageable (CAP-022, ADR-0023). See spec/21-collections.md §5.
// Conforms to: COL-016, COL-017, COL-018, COL-019, COL-020, COL-021.
//
// Clamping rules (mirror Pageable.swift / CAP-022):
//   - `pageSize` clamps to ≥ 0; `pageSize == 0` disables paging.
//   - `isPagingEnabled` is `pageSize > 0`.
//   - `pageCount` is `ceil(sourceCount / pageSize)` when paging is enabled
//     (0 for an empty source), else 1.
//   - `currentPageIndex` clamps to `[0, max(0, pageCount - 1)]`.
//     Re-clamps when `setSource(_:)` shrinks the source (COL-016).
//   - Navigation verbs are no-ops at the respective bounds (COL-018).
//   - Empty source + paging enabled: `pageCount == 0`, `currentPageIndex == 0`,
//     `items == []`, all navigation verbs are no-ops (COL-020).
//   - `pageSize == 0`: `isPagingEnabled == false`, `pageCount == 1`,
//     `items` yields all source items (COL-019).
//
// For filter-then-page (COL-021): subscribe to `SearchableState<TVM>.filtered`,
// capture the snapshot, and call `setSource(_:)` after each recompute.
//

import Combine

/// A paged view over a source array.
///
/// Decorates an array source with paging semantics, implementing `Pageable`
/// (CAP-022). The source is never mutated; replace it via `setSource(_:)`.
///
/// Thread safety: all access must be on the same thread.
public final class PagedComposition<TVM>: Pageable {

    // MARK: - Private state

    private var _source: [TVM]
    private var _pageSize: Int
    private var _currentPageIndex: Int = 0
    private let _propertyChangedSubject = PassthroughSubject<String, Never>()
    private var _sourceCancellables: Set<AnyCancellable> = []

    // MARK: - Init

    /// Creates a new paged composition.
    /// - Parameters:
    ///   - source: The initial source array of items. Never mutated internally.
    ///   - pageSize: Items per page. `0` (default) disables paging; negative
    ///               values are clamped to `0`.
    public init(source: [TVM] = [], pageSize: Int = 0) {
        self._source = source
        self._pageSize = max(0, pageSize)
    }

    // MARK: - Pageable

    /// Items per page. Setting to `0` disables paging. Negative assignments
    /// clamp to `0`. Re-clamps `currentPageIndex` when the page count changes.
    public var pageSize: Int {
        get { _pageSize }
        set {
            let clamped = max(0, newValue)
            guard _pageSize != clamped else { return }
            _pageSize = clamped
            _currentPageIndex = clampIndex(_currentPageIndex)
            _propertyChangedSubject.send("pageSize")
            _propertyChangedSubject.send("isPagingEnabled")
            _propertyChangedSubject.send("pageCount")
            _propertyChangedSubject.send("currentPageIndex")
            _propertyChangedSubject.send("items")
        }
    }

    /// Zero-based index of the currently visible page. Assignments outside
    /// `[0, pageCount - 1]` are clamped to the nearest bound.
    public var currentPageIndex: Int {
        get { _currentPageIndex }
        set {
            let clamped = clampIndex(newValue)
            guard _currentPageIndex != clamped else { return }
            _currentPageIndex = clamped
            _propertyChangedSubject.send("currentPageIndex")
            _propertyChangedSubject.send("items")
        }
    }

    /// `ceil(sourceCount / pageSize)` when paging is enabled (0 when source
    /// is empty); `1` when paging is disabled (`pageSize == 0`).
    public var pageCount: Int {
        if _pageSize == 0 { return 1 }
        let n = _source.count
        if n == 0 { return 0 }
        return (n + _pageSize - 1) / _pageSize
    }

    /// `true` when `pageSize > 0`.
    public var isPagingEnabled: Bool { _pageSize > 0 }

    /// Sets `currentPageIndex` to `0`. No-op when already at the first page.
    public func moveToFirstPage() {
        guard _currentPageIndex != 0 else { return }
        _currentPageIndex = 0
        _propertyChangedSubject.send("currentPageIndex")
        _propertyChangedSubject.send("items")
    }

    /// Decrements `currentPageIndex`. No-op when already at `0`.
    public func moveToPreviousPage() {
        guard _currentPageIndex > 0 else { return }
        _currentPageIndex -= 1
        _propertyChangedSubject.send("currentPageIndex")
        _propertyChangedSubject.send("items")
    }

    /// Increments `currentPageIndex`. No-op when already at `pageCount - 1`
    /// or when `pageCount == 0` (empty source).
    public func moveToNextPage() {
        let last = pageCount - 1
        guard _currentPageIndex < last else { return }
        _currentPageIndex += 1
        _propertyChangedSubject.send("currentPageIndex")
        _propertyChangedSubject.send("items")
    }

    /// Sets `currentPageIndex` to `pageCount - 1`. No-op when already last
    /// or when `pageCount == 0` (empty source).
    public func moveToLastPage() {
        let last = pageCount - 1
        guard _currentPageIndex < last else { return }
        _currentPageIndex = last
        _propertyChangedSubject.send("currentPageIndex")
        _propertyChangedSubject.send("items")
    }

    // MARK: - PagedComposition-specific surface

    /// Items on the current page.
    ///
    /// Returns all source items when paging is disabled (`pageSize == 0`).
    /// Returns an empty array when the source is empty.
    public var items: [TVM] {
        if _pageSize == 0 { return _source }
        if _source.isEmpty { return [] }
        let start = _currentPageIndex * _pageSize
        let end = min(start + _pageSize, _source.count)
        return Array(_source[start..<end])
    }

    /// Number of items on the current page (not the total source count).
    public var count: Int { items.count }

    /// Publisher that emits a property name whenever that property changes.
    public var propertyChanged: AnyPublisher<String, Never> {
        _propertyChangedSubject.eraseToAnyPublisher()
    }

    /// Replaces the source array, re-clamps `currentPageIndex`, and
    /// emits `propertyChanged` for the properties that changed.
    ///
    /// Call this after filtering (e.g. from `SearchableState.filtered`) to
    /// compose filter-then-page semantics (COL-021).
    public func setSource(_ newSource: [TVM]) {
        _source = newSource
        let clamped = clampIndex(_currentPageIndex)
        let indexChanged = clamped != _currentPageIndex
        if indexChanged { _currentPageIndex = clamped }
        _propertyChangedSubject.send("pageCount")
        if indexChanged { _propertyChangedSubject.send("currentPageIndex") }
        _propertyChangedSubject.send("items")
    }

    // MARK: - Private helpers

    /// Clamps `index` to `[0, max(0, pageCount - 1)]`.
    /// When `pageCount == 0` (empty source + paging enabled), index stays at 0.
    private func clampIndex(_ index: Int) -> Int {
        let maxIndex = max(0, pageCount - 1)
        if index < 0 { return 0 }
        if index > maxIndex { return maxIndex }
        return index
    }
}

public extension PagedComposition where TVM: ComponentVMBase {
    /// Creates a paged view over a CompositeVM source and refreshes the source
    /// snapshot whenever the composite emits `collectionChanged`.
    convenience init(sourceComposite: CompositeVM<TVM>, pageSize: Int = 0) {
        self.init(
            source: (0..<sourceComposite.count).map { sourceComposite.at($0) },
            pageSize: pageSize
        )
        sourceComposite.collectionChanged
            .sink { [weak self, weak sourceComposite] _ in
                guard let sourceComposite else { return }
                self?.setSource((0..<sourceComposite.count).map { sourceComposite.at($0) })
            }
            .store(in: &_sourceCancellables)
    }
}
