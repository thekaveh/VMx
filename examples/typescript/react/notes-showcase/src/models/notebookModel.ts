/**
 * NotebookModel — pure-data record for a notebook node.
 *
 * Immutable (readonly fields). `parentId` is null for root notebooks.
 * Identifiers are stable strings — same as C# / Python flavors so
 * cross-language parity audits compare identically.
 *
 * `isReadonly` (default `false`) marks a notebook whose notes cannot be
 * created or edited via the UI. When the currently-bound notebook is
 * readonly `CapabilityActionsVM` disables the *Add Note* action.
 */
export interface NotebookModel {
  readonly id: string;
  readonly name: string;
  readonly parentId: string | null;
  readonly isReadonly?: boolean;
}
