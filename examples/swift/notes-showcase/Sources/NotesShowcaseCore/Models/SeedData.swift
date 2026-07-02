import Foundation

/// Cross-language deterministic seed shared by every flavor of the showcase.
///
/// The same ids (`nb-*`, `note-NN`) and timestamps are used by the C#, Python,
/// and TypeScript flavors so cross-language audits compare identically.
/// Data-only — excluded from coverage threshold per plan §3.a.12.
public enum SeedData {
    /// Builds the canonical seed: 5 notebooks (1 nested), 12 notes, 3 starred.
    public static func build() -> (notebooks: [NotebookModel], notes: [NoteModel]) {
        // Deterministic base date so the audit hash is stable across runs.
        // Mirrors C# `new DateTimeOffset(2026, 5, 29, 12, 0, 0, TimeSpan.Zero)`.
        let fmt = ISO8601DateFormatter()
        let base = fmt.date(from: "2026-05-29T12:00:00Z")!

        let notebooks: [NotebookModel] = [
            NotebookModel(id: "nb-work",     name: "Work",     parentId: nil),
            NotebookModel(id: "nb-specs",    name: "Specs",    parentId: "nb-work"),
            NotebookModel(id: "nb-reviews",  name: "Reviews",  parentId: nil),
            NotebookModel(id: "nb-personal", name: "Personal", parentId: nil),
            NotebookModel(id: "nb-archive",  name: "Archive",  parentId: nil, isReadonly: true),
        ]

        var notes: [NoteModel] = []
        var idx = 1

        func add(_ notebookId: String, _ title: String, starred: Bool = false, tags: [String] = []) {
            // Mirrors C# `now.AddDays(-idx)` / `now.AddHours(-idx)`.
            let createdAt = base.addingTimeInterval(Double(-idx) * 86_400)
            let updatedAt = base.addingTimeInterval(Double(-idx) * 3_600)
            notes.append(NoteModel(
                id: String(format: "note-%02d", idx),
                notebookId: notebookId,
                title: title,
                tags: tags,
                body: "(seed body for \(title))",
                starred: starred,
                createdAt: createdAt,
                updatedAt: updatedAt
            ))
            idx += 1
        }

        add("nb-reviews", "Q1 design review")
        add("nb-reviews", "Auth migration plan",    starred: true, tags: ["security", "q2"])
        add("nb-reviews", "Vendor shortlist")
        add("nb-reviews", "Onboarding draft")
        add("nb-reviews", "Privacy review notes")
        add("nb-reviews", "Disaster recovery plan")
        add("nb-reviews", "Cross-team review log",  starred: true)
        add("nb-work",    "Standup notes")
        add("nb-work",    "Roadmap snapshot")
        add("nb-specs",   "MVx capability brief",   starred: true)
        add("nb-personal","Reading list")
        add("nb-personal","Travel ideas")

        return (notebooks: notebooks, notes: notes)
    }
}
