//
// CRUD capability micro-interfaces — `NewCreatable`, `Savable`, `Deletable`,
// `Updatable`.
//
// Ports langs/typescript/src/capabilities/crud.ts. See spec/14-capabilities.md
// §CRUD and spec/ADRs/0057-v3-capability-micro-interface-granularity.md.
//
// Per ADR-0057 the four CRUD verbs are kept as four independent, opt-in
// contracts — deliberately NOT collapsed into a single `Crud` interface. A VM
// advertises exactly the verbs it supports; e.g. a read-only list may implement
// none, a master list may implement `NewCreatable` + `Deletable` only.
//
// The three item-scoped verbs are generic over the item type. Swift protocols
// cannot be generic, so the parameter is modeled with `associatedtype Item`
// (mirroring the `<T>` of the TypeScript / C# flavors — see Filter.swift and the
// Task-10 ADR for the associatedtype-vs-generic divergence note).
//
// Swift idiom: bare protocol names (no `I`-prefix), camelCase members.
//

/// A VM that can create a new, blank item.
public protocol NewCreatable {
    /// Whether `createNew()` may currently be invoked.
    func canCreateNew() -> Bool
    /// Create a new item.
    func createNew()
}

/// A VM that can persist an item.
public protocol Savable {
    associatedtype Item
    /// Whether `save(_:)` may currently be invoked for `item`.
    func canSave(_ item: Item) -> Bool
    /// Persist `item`.
    func save(_ item: Item)
}

/// A VM that can delete an item.
public protocol Deletable {
    associatedtype Item
    /// Whether `delete(_:)` may currently be invoked for `item`.
    func canDelete(_ item: Item) -> Bool
    /// Delete `item`.
    func delete(_ item: Item)
}

/// A VM that can update an item.
public protocol Updatable {
    associatedtype Item
    /// Whether `update(_:)` may currently be invoked for `item`.
    func canUpdate(_ item: Item) -> Bool
    /// Update `item`.
    func update(_ item: Item)
}
