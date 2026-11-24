//
// ScoredFilteredCompositeVM.swift — score-ranked visible projection.
//

public final class ScoredFilteredCompositeVM<Child: ComponentVMBase>: FilteredCompositeVM<Child> {
    private let scorer: (Child) -> Double?

    public init(
        _ source: CompositeVM<Child>,
        cursorPolicy: FilteredCursorPolicy = .snapToFirst,
        scorer: @escaping (Child) -> Double?
    ) {
        self.scorer = scorer
        super.init(
            source,
            cursorPolicy: cursorPolicy,
            predicate: { scorer($0) != nil },
            deferInitialRecompute: true
        )
        refreshScores()
    }

    /// Enumerates one `snapshot()` and calls `scorer` once per child, so each
    /// score belongs to the child it is paired with (ADR-0187).
    public override func orderedVisible() -> [Child] {
        source.snapshot().enumerated()
            .map { (index: $0.offset, vm: $0.element, score: scorer($0.element)) }
            .filter { $0.score != nil }
            .sorted {
                if $0.score! == $1.score! { return $0.index < $1.index }
                return $0.score! > $1.score!
            }
            .map(\.vm)
    }

    public func refreshScores() {
        recompute()
    }
}
