import Foundation

/// Domain model for a notebook (a node in the notebooks tree).
///
/// See spec/proposals/2026-05-29-notes-showcase-scenario.md §3.1.
/// Pure data — no behavior, no VMx dependencies.
public struct NotebookModel: Sendable, Equatable, Codable {
    public let id: String
    public let name: String
    public let parentId: String?

    public init(id: String, name: String, parentId: String?) {
        self.id = id
        self.name = name
        self.parentId = parentId
    }
}
