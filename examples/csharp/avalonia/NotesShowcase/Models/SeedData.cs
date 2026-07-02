namespace NotesShowcase.Models;

/// <summary>
/// Cross-language deterministic seed shared by every flavor of the showcase.
///
/// Same ids (notebook ids <c>nb-*</c>, note ids <c>note-NN</c>) are used by the
/// Python and TypeScript flavors so cross-language audits compare identically.
/// Data-only — excluded from coverage threshold per plan §3.a.12.
/// </summary>
public static class SeedData
{
    /// <summary>Builds the canonical seed: 5 notebooks (1 nested), 12 notes, 3 starred.</summary>
    public static (IReadOnlyList<NotebookModel> Notebooks, IReadOnlyList<NoteModel> Notes) Build()
    {
        // Deterministic "now" so the audit hash is stable across runs; offsets are
        // applied per note below.
        var now = new DateTimeOffset(2026, 5, 29, 12, 0, 0, TimeSpan.Zero);

        var notebooks = new List<NotebookModel>
        {
            new("nb-work",     "Work",     null),
            new("nb-specs",    "Specs",    "nb-work"),
            new("nb-reviews",  "Reviews",  null),
            new("nb-personal", "Personal", null),
            new("nb-archive",  "Archive",  null, IsReadOnly: true),
        };

        var notes = new List<NoteModel>();
        var idx = 1;
        void Add(string nb, string title, bool starred = false, params string[] tags)
        {
            notes.Add(new NoteModel(
                Id: $"note-{idx:D2}",
                NotebookId: nb,
                Title: title,
                Tags: tags,
                Body: $"(seed body for {title})",
                Starred: starred,
                CreatedAt: now.AddDays(-idx),
                UpdatedAt: now.AddHours(-idx)));
            idx++;
        }

        Add("nb-reviews", "Q1 design review");
        Add("nb-reviews", "Auth migration plan", starred: true, "security", "q2");
        Add("nb-reviews", "Vendor shortlist");
        Add("nb-reviews", "Onboarding draft");
        Add("nb-reviews", "Privacy review notes");
        Add("nb-reviews", "Disaster recovery plan");
        Add("nb-reviews", "Cross-team review log", starred: true);
        Add("nb-work", "Standup notes");
        Add("nb-work", "Roadmap snapshot");
        Add("nb-specs", "MVx capability brief", starred: true);
        Add("nb-personal", "Reading list");
        Add("nb-personal", "Travel ideas");

        return (notebooks, notes);
    }
}
