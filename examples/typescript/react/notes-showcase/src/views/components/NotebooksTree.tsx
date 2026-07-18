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
  const selectTreeItem = (item: HTMLElement | undefined): void => {
    const notebook = root.all.find((candidate) => candidate.model.id === item?.dataset.notebookId);
    if (notebook !== undefined) ws.selectNotebook(notebook);
  };
  const onTreeKeyDown = (e: React.KeyboardEvent<HTMLUListElement>): void => {
    const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="treeitem"]'));
    if (items.length === 0) return;
    const current = items.find((item) => item.getAttribute("aria-selected") === "true") ?? items[0];
    if (current === undefined) return;
    const index = items.indexOf(current);
    let target: HTMLElement | undefined;
    switch (e.key) {
      case "ArrowDown":
        target = items[Math.min(index + 1, items.length - 1)];
        break;
      case "ArrowUp":
        target = items[Math.max(index - 1, 0)];
        break;
      case "Home":
        target = items[0];
        break;
      case "End":
        target = items.at(-1);
        break;
      case "ArrowRight": {
        const notebook = root.all.find((candidate) => candidate.model.id === current.dataset.notebookId);
        if (current.getAttribute("aria-expanded") === "false") {
          notebook?.toggleExpansion();
        } else if (current.getAttribute("aria-expanded") === "true") {
          target = current.querySelector<HTMLElement>('[role="group"] > [role="treeitem"]') ?? undefined;
        }
        break;
      }
      case "ArrowLeft": {
        const notebook = root.all.find((candidate) => candidate.model.id === current.dataset.notebookId);
        if (current.getAttribute("aria-expanded") === "true") {
          notebook?.toggleExpansion();
        } else {
          target = current.parentElement?.closest<HTMLElement>('[role="treeitem"]') ?? undefined;
        }
        break;
      }
      case "Enter":
      case " ":
        target = current;
        break;
      default:
        return;
    }
    e.preventDefault();
    selectTreeItem(target);
  };

  return (
    <ul
      role="tree"
      aria-label="Notebooks"
      aria-activedescendant={root.current === null ? undefined : `notebook-${root.current.model.id}`}
      tabIndex={0}
      onKeyDown={onTreeKeyDown}
      style={{ listStyle: "none", padding: 0, margin: 0 }}
    >
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
    if (liveNb.isExpanded && liveRoot.current !== null) {
      let parentId = liveRoot.current.model.parentId;
      while (parentId !== null) {
        if (parentId === nb.model.id) {
          ws.selectNotebook(nb);
          break;
        }
        parentId = root.all.find((candidate) => candidate.model.id === parentId)?.model.parentId ?? null;
      }
    }
    nb.toggleExpansion();
  };

  return (
    <li
      id={`notebook-${nb.model.id}`}
      data-notebook-id={nb.model.id}
      role="treeitem"
      aria-level={level}
      aria-expanded={hasChildren ? liveNb.isExpanded : undefined}
      aria-selected={isCurrent}
    >
      <div
        className={`notebooks-tree-node${isCurrent ? " is-current" : ""}`}
        onClick={onSelect}
      >
        <button
          type="button"
          tabIndex={-1}
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
