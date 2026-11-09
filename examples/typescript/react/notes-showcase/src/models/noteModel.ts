/**
 * NoteModel — pure-data record for a single note.
 *
 * Immutable. `tags` is a readonly tuple-like array. `createdAt` / `updatedAt`
 * are ISO-8601 strings (mirrors the C# DateTimeOffset round-trip format and
 * the Python isoformat representation — same shape across all four UI-backed showcase examples).
 */
export interface NoteModel {
  readonly id: string;
  readonly notebookId: string;
  readonly title: string;
  readonly tags: readonly string[];
  readonly body: string;
  readonly starred: boolean;
  readonly createdAt: string;
  readonly updatedAt: string;
}

/**
 * The search rule of every notes showcase, for the notes list and the global
 * search alike. The term is trimmed, and an empty term matches every note.
 * Otherwise a note matches when its title, its body or one of its tags
 * contains the term, ignoring case. Each field is matched on its own, so a
 * term never spans two fields.
 */
export function noteMatches(note: NoteModel, term: string): boolean {
  const needle = term.trim().toLowerCase();
  if (needle.length === 0) return true;
  return (
    note.title.toLowerCase().includes(needle) ||
    note.body.toLowerCase().includes(needle) ||
    note.tags.some((tag) => tag.toLowerCase().includes(needle))
  );
}
