/**
 * NoteForm — note editor (right pane).
 *
 * See plan §5.c (two-way form gap fix, parity with Phase 5.b Textual).
 *
 * Pure-VM contract (§6.1): no React state. All input values come directly
 * from `ws.noteForm.draft` (re-rendered via `useVm`) and write back through
 * the form's two-way `draft` setter (`NoteFormVM.draft = { …, title }`). This
 * is the exact pattern the Avalonia and Textual flavors converged on after
 * Phase 5.a flagged that the title input wasn't editable.
 *
 * Save / Revert / Delete bind to commands via `useCommand`. Delete is wired
 * through `ws.notesView.current?.deleteCommand` — Phase 3.c left
 * `NoteVM.onDelete` as a host-supplied callback; here, "Delete" simply
 * re-loads the notebook to reflect any deletion the repo performed.
 */
import type React from "react";

import { useCommand } from "../adapter/useCommand.js";
import { useVm } from "../adapter/useVm.js";
import type { WorkspaceVM } from "../../viewmodels/workspaceVM.js";

export interface NoteFormProps {
  readonly ws: WorkspaceVM;
}

export const NoteForm: React.FC<NoteFormProps> = ({ ws }) => {
  const form = useVm(ws.noteForm);
  const save = useCommand(ws.noteForm.approveCommand);
  const revert = useCommand(ws.noteForm.denyCommand);
  const addTag = useCommand(ws.noteForm.addTagCommand);
  const showEdit = useCommand(ws.noteForm.showEditModeCommand);
  const showPreview = useCommand(ws.noteForm.showPreviewModeCommand);

  if (!form.hasBoundNote) {
    return <p className="note-form-status">No note selected.</p>;
  }

  const draft = form.draft;

  const onTitleChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    ws.noteForm.draft = { ...draft, title: e.target.value };
  };
  const onBodyChange = (e: React.ChangeEvent<HTMLTextAreaElement>): void => {
    ws.noteForm.draft = { ...draft, body: e.target.value };
  };
  const onStarredChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    ws.noteForm.draft = { ...draft, starred: e.target.checked };
  };
  const onTagDraftChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    ws.noteForm.tagDraft = e.target.value;
  };
  const onTagDraftKeyDown = (e: React.KeyboardEvent<HTMLInputElement>): void => {
    if (e.key === "Enter" && addTag.canExecute) {
      e.preventDefault();
      addTag.execute();
    }
  };
  const onRemoveTag = (tag: string): void => {
    ws.noteForm.removeTagCommand.execute(tag);
  };

  return (
    <form
      className="note-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (save.canExecute) save.execute();
      }}
    >
      <div className="note-form-row">
        <label htmlFor="note-form-title">Title</label>
        <input
          id="note-form-title"
          type="text"
          value={draft.title}
          onChange={onTitleChange}
          aria-invalid={form.titleError !== null}
          aria-describedby={form.titleError === null ? undefined : "note-form-title-error"}
        />
        {form.titleError !== null ? (
          <span id="note-form-title-error" className="note-form-error">
            {form.titleError}
          </span>
        ) : null}
      </div>
      <div className="note-form-row">
        <label htmlFor="note-form-tags">Tags</label>
        <div className="note-form-tags" id="note-form-tags">
          {draft.tags.map((tag) => (
            <span key={tag} className="note-form-tag">
              {tag}
              <button
                type="button"
                aria-label={`Remove tag ${tag}`}
                onClick={() => onRemoveTag(tag)}
              >
                ×
              </button>
            </span>
          ))}
          <input
            type="text"
            placeholder="add tag"
            value={form.tagDraft}
            onChange={onTagDraftChange}
            onKeyDown={onTagDraftKeyDown}
            aria-label="Add tag"
            style={{ flex: "0 0 100px" }}
          />
        </div>
        {form.tagSuggestions.length > 0 ? (
          <div className="note-form-suggestions" aria-label="Tag suggestions">
            {form.tagSuggestions.map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </div>
        ) : null}
      </div>
      <div className="note-form-row">
        <div className="note-form-mode-row">
          <label htmlFor="note-form-body">Body</label>
          <span>
            <button type="button" onClick={showEdit.execute} disabled={!showEdit.canExecute}>
              Edit
            </button>
            <button type="button" onClick={showPreview.execute} disabled={!showPreview.canExecute}>
              Preview
            </button>
          </span>
        </div>
        {form.isPreviewMode ? (
          <div id="note-form-body" className="note-form-body note-form-preview">
            {draft.body || "No body."}
          </div>
        ) : (
          <textarea
            id="note-form-body"
            className="note-form-body"
            value={draft.body}
            onChange={onBodyChange}
          />
        )}
      </div>
      <label className="note-form-status">
        <input type="checkbox" checked={draft.starred} onChange={onStarredChange} />{" "}
        Starred
      </label>
      <p className="note-form-status">
        {form.isDirty ? "Modified" : "Saved"}
        {form.isValid ? "" : ` · ${form.titleError ?? "invalid"}`}
      </p>
      <div className="note-form-buttons">
        <button type="submit" disabled={!save.canExecute}>Save</button>
        <button type="button" onClick={revert.execute} disabled={!revert.canExecute}>
          Revert
        </button>
      </div>
    </form>
  );
};
