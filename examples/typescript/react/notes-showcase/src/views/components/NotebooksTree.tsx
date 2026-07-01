/**
 * NotebooksTree — recursive notebooks tree (left pane).
 *
 * See plan §5.c (hierarchy gap explicit fix per Phase 5.b parity). The Phase
 * 5.a Avalonia UI flagged that nested children were not rendered; Phase 5.b
 * Textual addressed it by recursing on `notebooks.children_of(node)`. This
 * component does the analogous thing using `notebooks.childrenOf(nb)` from
 * `NotebooksRootVM`.
 *
 * Pure-VM contract (§6.1): no React state. Selection writes back to
 * `ws.notebooksRoot.current` in a one-liner; expansion toggles invoke
 * `nb.toggleExpansion()` directly (the same call the
 * `IExpansionTogglable` capability bridge would dispatch).
 */
import type React from "react";

import { useVm } from "../adapter/useVm.js";
import type { NotebookVM } from "../../viewmodels/notebookVM.js";
import type { NotebooksRootVM } from "../../viewmodels/notebooksRootVM.js";
import type { WorkspaceVM } from "../../viewmodels/workspaceVM.js";

export interface NotebooksTreeProps {
  readonly ws: WorkspaceVM;
}

export const NotebooksTree: React.FC<NotebooksTreeProps> = ({ ws }) => {
  // Subscribe to the root VM so `current` selection re-renders the whole tree
  // (cheap — the tree is tiny). Each child node uses its own `useVm` for
  // expansion / model changes, so unrelated nodes don't re-render.
  const root = useVm(ws.notebooksRoot);

  return (
    <ul role="tree" aria-label="Notebooks" style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {root.roots.map((nb) => (
        <NotebookTreeNode key={nb.model.id} ws={ws} nb={nb} level={1} />
      ))}
    </ul>
  );
};

interface NotebookTreeNodeProps {
  readonly ws: WorkspaceVM;
  readonly nb: NotebookVM;
  readonly level: number;
}

const NotebookTreeNode: React.FC<NotebookTreeNodeProps> = ({ ws, nb, level }) => {
  const root: NotebooksRootVM = ws.notebooksRoot;
  const liveNb = useVm(nb);
  const liveRoot = useVm(root);
  const children = root.childrenOf(nb);
  const hasChildren = children.length > 0;
  const isCurrent = liveRoot.current === nb;

  const onSelect = (): void => {
    ws.selectNotebook(nb);
  };

  const onToggle = (e: React.MouseEvent): void => {
    e.stopPropagation();
    nb.toggleExpansion();
  };
  const onNodeKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect();
    } else if (e.key === "ArrowRight" && hasChildren && !liveNb.isExpanded) {
      e.preventDefault();
      nb.toggleExpansion();
    } else if (e.key === "ArrowLeft" && hasChildren && liveNb.isExpanded) {
      e.preventDefault();
      nb.toggleExpansion();
    }
  };

  return (
    <li
      role="treeitem"
      aria-level={level}
      aria-expanded={hasChildren ? liveNb.isExpanded : undefined}
      aria-selected={isCurrent}
    >
      <div
        className={`notebooks-tree-node${isCurrent ? " is-current" : ""}`}
        tabIndex={0}
        onClick={onSelect}
        onKeyDown={onNodeKeyDown}
      >
        <button
          type="button"
          className="notebooks-tree-toggle"
          aria-label={liveNb.isExpanded ? `Collapse ${liveNb.notebookName}` : `Expand ${liveNb.notebookName}`}
          disabled={!hasChildren}
          onClick={hasChildren ? onToggle : undefined}
        >
          {hasChildren ? (liveNb.isExpanded ? "▼" : "▶") : ""}
        </button>
        <span>{liveNb.notebookName}</span>
      </div>
      {hasChildren && liveNb.isExpanded && (
        <ul className="notebooks-tree-children" role="group">
          {children.map((child) => (
            <NotebookTreeNode key={child.model.id} ws={ws} nb={child} level={level + 1} />
          ))}
        </ul>
      )}
    </li>
  );
};
