//
// Filter capability micro-interface — `Filterable`.
//
// Ports langs/typescript/src/capabilities/filter.ts. See
// spec/14-capabilities.md §2.6 and ADR-0022 / ADR-0057.
//
// DIVERGENCE (ADR-0059 §2.3): TypeScript's
// `IFilterable<T>` parameterizes the interface itself; Swift protocols cannot be
// generic, so the item type is expressed as an `associatedtype Item`. The
// semantics are identical — a settable `(Item) -> Bool` predicate where `nil`
// means "no filter applied". The trade-off is that `Filterable` becomes a
// PAT (protocol with associated type): it can be used as a generic constraint
// but not as an existential `any Filterable` without binding `Item`.
//
// Swift idiom: bare protocol name (no `I`-prefix), camelCase members.
//
public protocol Filterable {
    /// The element type this filter operates on.
    associatedtype Item
    /// The current filter predicate; `nil` means no filter is applied. Setting
    /// the predicate (or clearing it to `nil`) is the implementer's trigger to
    /// re-filter.
    var filter: ((Item) -> Bool)? { get set }
    /// Whether filtering is currently allowed.
    func canFilter() -> Bool
}
