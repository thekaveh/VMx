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

    public override func orderedVisible() -> [Child] {
        (0..<source.count)
            .map { (index: $0, vm: source.at($0), score: scorer(source.at($0))) }
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
