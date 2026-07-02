/**
 * NotesList — centre pane (search + starred filter + paged list).
 *
 * See plan §5.c. Mirrors:
 *   - `examples/csharp/avalonia/NotesShowcase/Views/NotesListView.axaml`.
 *   - `examples/python/textual/notes_showcase/src/notes_showcase/views/notes_list.py`.
 *
 * Pure-VM contract (§6.1): no React state. The search input value is read
 * directly from `ws.notesView.searchTerm` (re-rendered via `useVm`) and the
 * `onChange` handler writes back to the same setter — two-way binding without
 * a `useState`. Pagination buttons use `useCommand`. Selecting a note writes
 * to `ws.notesView.current`; the WorkspaceVM-level subscription (see
 * `workspaceVM.ts` R3-Crit2 wiring) observes the resulting
 * `PropertyChangedMessage` and rebinds the form on the foreground
 * scheduler. The React handler is therefore VM-only (no direct
 * `noteForm.bindTo` call) — R5 Minor (Agent D, M-D1) removed the prior
 * direct bind here to stop the double-bind that churned subscriptions and
 * doubled every PropertyChanged emission for downstream consumers.
 */
import type React from "react";

import { useCommand } from "../adapter/useCommand.js";
import { useDerivedProperty } from "../adapter/useDerivedProperty.js";
import { useVm } from "../adapter/useVm.js";
import type { NoteVM } from "../../viewmodels/noteVM.js";
import type { WorkspaceVM } from "../../viewmodels/workspaceVM.js";

export interface NotesListProps {
  readonly ws: WorkspaceVM;
}

export const NotesList: React.FC<NotesListProps> = ({ ws }) => {
  const notesView = useVm(ws.notesView);
  const pageLabel = useDerivedProperty(ws.notesView.pageLabelDerived);
  const moveFirst = useCommand(ws.notesView.moveToFirstPageCommand);
  const movePrev = useCommand(ws.notesView.moveToPreviousPageCommand);
  const moveNext = useCommand(ws.notesView.moveToNextPageCommand);
  const moveLast = useCommand(ws.notesView.moveToLastPageCommand);

  const onSearchChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    ws.notesView.searchTerm = e.target.value;
  };
  const onStarredChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    ws.notesView.showStarredOnly = e.target.checked;
  };
  const onSelect = (note: NoteVM): void => {
    // R5 Minor (Agent D, M-D1): do NOT call ``ws.noteForm.bindTo`` here.
    // The WorkspaceVM-level subscription on ``notesView.current`` (added
    // in R3-Crit2 and wired through observeOn(foreground) in R4-Imp2)
    // already rebinds the form. Calling bindTo here in addition was a
    // double-bind: it disposed and recreated the inner FormVM /
    // subscriptions, then the VM subscription immediately did it again,
    // doubling every PropertyChanged emission for downstream consumers.
    ws.notesView.current = note;
    ws.setFocus(note);
  };

  return (
    <div>
      <div className="notes-list-search">
        <input
          type="search"
          aria-label="Search notes"
          placeholder="Search…"
          value={notesView.searchTerm}
          onChange={onSearchChange}
        />
      </div>
      <label className="notes-list-starred">
        <input
          type="checkbox"
          checked={notesView.showStarredOnly}
          onChange={onStarredChange}
        />
        Starred only
      </label>
      <ul className="notes-list" role="listbox" aria-label="Notes">
        {notesView.visibleItems.map((note) => (
          <NotesListItem
            key={note.noteId}
            note={note}
            isCurrent={notesView.current === note}
            onSelect={onSelect}
          />
        ))}
      </ul>
      <div className="notes-list-pagination">
        <button type="button" aria-label="First page" onClick={moveFirst.execute} disabled={!moveFirst.canExecute}>⏮</button>
        <button type="button" aria-label="Previous page" onClick={movePrev.execute} disabled={!movePrev.canExecute}>◀</button>
        <span>{pageLabel ?? "Page —"}</span>
        <button type="button" aria-label="Next page" onClick={moveNext.execute} disabled={!moveNext.canExecute}>▶</button>
        <button type="button" aria-label="Last page" onClick={moveLast.execute} disabled={!moveLast.canExecute}>⏭</button>
      </div>
    </div>
  );
};

interface NotesListItemProps {
  readonly note: NoteVM;
  readonly isCurrent: boolean;
  readonly onSelect: (note: NoteVM) => void;
}

const NotesListItem: React.FC<NotesListItemProps> = ({ note, isCurrent, onSelect }) => {
  const liveNote = useVm(note);
  const onKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(note);
    }
  };

  return (
    <li
      role="option"
      aria-selected={isCurrent}
      className={`notes-list-item${isCurrent ? " is-current" : ""}`}
      tabIndex={0}
      onClick={() => onSelect(note)}
      onKeyDown={onKeyDown}
    >
      {liveNote.starred && <span className="notes-list-item-star" aria-label="Starred">★</span>}
      <span>{liveNote.title}</span>
    </li>
  );
};
