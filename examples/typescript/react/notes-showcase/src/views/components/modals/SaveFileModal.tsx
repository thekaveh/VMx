/**
 * SaveFileModal — save-as / open dialog.
 *
 * See plan §5.c. The file-name input is *uncontrolled* (a `defaultValue` and
 * a `name` attribute) so the modal can capture the typed value at submit time
 * via `FormData` without holding React state — keeping §6.1 Pure-VM contract.
 *
 * On submit, calls `request.resolveString(name)`; on cancel, resolves with
 * `null` (per `IDialogService.pickFileToSave` contract).
 */
import type React from "react";

import type { DialogRequest } from "../../adapter/ReactDialogService.js";

export const SaveFileModal: React.FC<{ request: DialogRequest }> = ({ request }) => {
  const onSubmit = (e: React.FormEvent<HTMLFormElement>): void => {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const value = data.get("filename");
    const name = typeof value === "string" ? value.trim() : "";
    request.resolveString(name.length > 0 ? name : null);
  };
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true">
      <form className="dialog-window" onSubmit={onSubmit}>
        <div className="dialog-title">{request.title ?? request.message}</div>
        <label htmlFor="dialog-filename">Filename</label>
        <input
          id="dialog-filename"
          name="filename"
          type="text"
          defaultValue={request.suggestedName ?? ""}
          autoFocus
        />
        <div className="dialog-buttons">
          <button type="button" onClick={() => request.resolveString(null)}>Cancel</button>
          <button type="submit">Save</button>
        </div>
      </form>
    </div>
  );
};
