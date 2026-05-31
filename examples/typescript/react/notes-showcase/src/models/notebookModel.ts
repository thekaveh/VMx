/**
 * NotebookModel — pure-data record for a notebook node.
 *
 * Immutable (readonly fields). `parentId` is null for root notebooks.
 * Identifiers are stable strings — same as C# / Python flavors so
 * cross-language parity audits compare identically.
 */
export interface NotebookModel {
  readonly id: string;
  readonly name: string;
  readonly parentId: string | null;
}
