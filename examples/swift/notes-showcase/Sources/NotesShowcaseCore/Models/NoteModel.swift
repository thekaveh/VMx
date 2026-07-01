import Foundation

/// Domain model for a single note.
///
/// See spec/proposals/2026-05-29-notes-showcase-scenario.md §3.2.
/// Pure data — no behavior, no VMx dependencies.
///
/// Custom `Equatable` compares `tags` element-wise so that
/// `FormVM<NoteModel>.isDirty` correctly reads clean after a deep snapshot
/// round-trip. (In the C# flavor a record's synthesised equality compares the
/// list by reference; Swift's `[String] ==` is already element-wise, but the
/// explicit conformance makes the intent explicit and mirrors the C# hook.)
public struct NoteModel: Sendable, Codable {
    public let id: String
    public let notebookId: String
    public let title: String
    public let tags: [String]
    public let body: String
    public let starred: Bool
    public let createdAt: Date
    public let updatedAt: Date

    public init(
        id: String,
        notebookId: String,
        title: String,
        tags: [String],
        body: String,
        starred: Bool,
        createdAt: Date,
        updatedAt: Date
    ) {
        self.id = id
        self.notebookId = notebookId
        self.title = title
        self.tags = tags
        self.body = body
        self.starred = starred
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    /// Returns a copy with the specified fields overridden.
    /// Use this to make edits — mirrors the C# `record with { … }` syntax.
    public func with(
        notebookId: String? = nil,
        title: String? = nil,
        tags: [String]? = nil,
        body: String? = nil,
        starred: Bool? = nil,
        updatedAt: Date? = nil
    ) -> NoteModel {
        NoteModel(
            id: self.id,
            notebookId: notebookId ?? self.notebookId,
            title: title ?? self.title,
            tags: tags ?? self.tags,
            body: body ?? self.body,
            starred: starred ?? self.starred,
            createdAt: self.createdAt,
            updatedAt: updatedAt ?? self.updatedAt
        )
    }
}

extension NoteModel: Equatable {
    /// Value equality with element-wise `tags` comparison.
    /// Replaces the default synthesised equality to mirror the C# custom Equals.
    public static func == (lhs: NoteModel, rhs: NoteModel) -> Bool {
        lhs.id == rhs.id
            && lhs.notebookId == rhs.notebookId
            && lhs.title == rhs.title
            && lhs.body == rhs.body
            && lhs.starred == rhs.starred
            && lhs.createdAt == rhs.createdAt
            && lhs.updatedAt == rhs.updatedAt
            && lhs.tags == rhs.tags
    }
}
