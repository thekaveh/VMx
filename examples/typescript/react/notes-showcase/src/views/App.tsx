/**
 * App — root React component for the Notes Workspace.
 *
 * See plan §5.c. Mirrors `examples/csharp/avalonia/NotesShowcase/Views/App.axaml`
 * and `examples/python/textual/notes_showcase/src/notes_showcase/views/app.py`.
 *
 * Construction is delegated to `main.tsx` (composition root). This component
 * subscribes to the `WorkspaceVM` once via `useVm` so that hub events on the
 * aggregate (rare — most reactivity happens deeper in child components) still
 * propagate to the top of the tree.
 *
 * The dialog service is threaded through to `Layout` because `DialogOverlay`
 * needs the service instance to bind its `BehaviorSubject<DialogRequest|null>`.
 */
import type React from "react";

import { useVm } from "./adapter/useVm.js";
import { useThemeAdapter } from "./adapter/themeAdapter.js";
import type { ReactDialogService } from "./adapter/ReactDialogService.js";
import { Layout } from "./components/Layout.js";
import type { WorkspaceVM } from "../viewmodels/workspaceVM.js";

export interface AppProps {
  readonly workspace: WorkspaceVM;
  readonly dialog: ReactDialogService;
}

export const App: React.FC<AppProps> = ({ workspace, dialog }) => {
  const ws = useVm(workspace);
  // VMX-129: drive the document theme from the workspace-owned ThemeVM
  // (THEME-001..005). The hook applies the current palette on mount and
  // re-applies on every effective change for the app's lifetime.
  useThemeAdapter(ws.theme);
  return <Layout ws={ws} dialog={dialog} />;
};
