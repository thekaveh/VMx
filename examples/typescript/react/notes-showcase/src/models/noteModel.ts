/**
 * NoteModel — pure-data record for a single note.
 *
 * Immutable. `tags` is a readonly tuple-like array. `createdAt` / `updatedAt`
 * are ISO-8601 strings (mirrors the C# DateTimeOffset round-trip format and
 * the Python isoformat representation — same shape across all three flavors).
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
