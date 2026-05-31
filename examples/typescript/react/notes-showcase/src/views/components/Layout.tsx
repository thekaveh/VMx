/**
 * Layout — 3-pane Notes Workspace shell.
 *
 * See scenario doc §5.1 (layout) and plan §5.c. Mirrors:
 *   - `examples/csharp/avalonia/NotesShowcase/Views/MainWindow.axaml`.
 *   - `examples/python/textual/notes_showcase/src/notes_showcase/views/main_screen.py`.
 *
 * Pure-VM contract (§6.1): this component holds no React state. The toolbar
 * commands come straight off `ws.newNotebookCommand` / `ws.newNoteCommand`
 * / `ws.exportCommand` via `useCommand`; the keymap is forwarded to
 * `useHotkeys`. All children get the bound sub-VM from the prop tree.
 */
import type React from "react";

import { useCommand } from "../adapter/useCommand.js";
import type { ReactDialogService } from "../adapter/ReactDialogService.js";
import type { WorkspaceVM } from "../../viewmodels/workspaceVM.js";
import { useHotkeys } from "../hooks/useHotkeys.js";
import { CapabilityActions } from "./CapabilityActions.js";
import { DialogOverlay } from "./DialogOverlay.js";
import { NoteForm } from "./NoteForm.js";
import { NotebooksTree } from "./NotebooksTree.js";
import { NotesList } from "./NotesList.js";
import { Notifications } from "./Notifications.js";
import { StatusBar } from "./StatusBar.js";

export interface LayoutProps {
  readonly ws: WorkspaceVM;
  readonly dialog: ReactDialogService;
}

export const Layout: React.FC<LayoutProps> = ({ ws, dialog }) => {
  const newNotebook = useCommand(ws.newNotebookCommand);
  const newNote = useCommand(ws.newNoteCommand);
  const exportCmd = useCommand(ws.exportCommand);

  // Hotkeys: Mod+N new note, Mod+Shift+N new notebook, Mod+E export.
  useHotkeys({
    "Mod+N": () => newNote.canExecute && newNote.execute(),
    "Mod+Shift+N": () => newNotebook.canExecute && newNotebook.execute(),
    "Mod+E": () => exportCmd.canExecute && exportCmd.execute(),
  });

  return (
    <div className="workspace-layout">
      <div className="workspace-toolbar" role="toolbar" aria-label="Workspace toolbar">
        <button
          type="button"
          onClick={newNotebook.execute}
          disabled={!newNotebook.canExecute}
        >
          + Notebook
        </button>
        <button
          type="button"
          onClick={newNote.execute}
          disabled={!newNote.canExecute}
        >
          + Note
        </button>
        <button
          type="button"
          onClick={exportCmd.execute}
          disabled={!exportCmd.canExecute}
        >
          Export…
        </button>
      </div>
      <div className="workspace-main">
        <section className="workspace-pane" aria-label="Notebooks">
          <header className="workspace-pane-header">Notebooks</header>
          <div className="workspace-pane-body">
            <NotebooksTree ws={ws} />
          </div>
        </section>
        <section className="workspace-pane" aria-label="Notes">
          <header className="workspace-pane-header">Notes</header>
          <div className="workspace-pane-body">
            <NotesList ws={ws} />
          </div>
        </section>
        <section className="workspace-pane" aria-label="Note details">
          <header className="workspace-pane-header">Note</header>
          <div className="workspace-pane-body">
            <NoteForm ws={ws} />
          </div>
        </section>
      </div>
      <CapabilityActions ws={ws} />
      <StatusBar ws={ws} />
      <Notifications ws={ws} />
      <DialogOverlay service={dialog} />
    </div>
  );
};
