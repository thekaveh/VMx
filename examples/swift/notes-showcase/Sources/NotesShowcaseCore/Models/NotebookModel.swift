import Foundation

/// Domain model for a notebook (a node in the notebooks tree).
///
/// See spec/proposals/2026-05-29-notes-showcase-scenario.md §5.3.
/// Pure data — no behavior, no VMx dependencies.
public struct NotebookModel: Sendable, Equatable, Codable {
    public let id: String
    public let name: String
    public let parentId: String?
    public let isReadonly: Bool

    public init(id: String, name: String, parentId: String?, isReadonly: Bool = false) {
        self.id = id
        self.name = name
        self.parentId = parentId
        self.isReadonly = isReadonly
    }
}
