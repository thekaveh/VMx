import type React from "react";

import { useCommand } from "../adapter/useCommand.js";
import { useVm } from "../adapter/useVm.js";
import type { WorkspaceVM } from "../../viewmodels/workspaceVM.js";

export interface GlobalSearchProps {
  readonly ws: WorkspaceVM;
}

export const GlobalSearch: React.FC<GlobalSearchProps> = ({ ws }) => {
  const vm = useVm(ws.globalSearch);
  const refresh = useCommand(vm.refreshCommand);
  const loadMore = useCommand(vm.loadMoreCommand);

  const onSearchChange = (e: React.ChangeEvent<HTMLInputElement>): void => {
    vm.searchTerm = e.target.value;
    vm.search();
  };

  return (
    <section className="global-search" aria-label="Global search">
      <div className="global-search-controls">
        <input
          type="search"
          aria-label="Search all notes"
          placeholder="Search all notes…"
          value={vm.searchTerm}
          onChange={onSearchChange}
        />
        <button type="button" onClick={refresh.execute} disabled={!refresh.canExecute}>
          Search
        </button>
      </div>
      <ul className="global-search-results" aria-label="Global search results">
        {vm.results.map((note) => (
          <li key={note.noteId}>
            <span>{note.title}</span>
            <small>{note.model.notebookId}</small>
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="global-search-more"
        onClick={loadMore.execute}
        disabled={!loadMore.canExecute}
      >
        Load more
      </button>
    </section>
  );
};
