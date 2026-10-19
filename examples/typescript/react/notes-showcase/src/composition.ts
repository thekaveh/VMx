/**
 * composition — builds the app's object graph. `main.tsx` mounts the result;
 * tests build the same graph (with zero repository delays) to drive the real
 * wiring, including the browser export path.
 */
import {
  InMemoryNoteRepository,
  type InMemoryRepositoryOptions,
} from "./models/inMemoryRepository.js";
import { buildSeed } from "./models/seed.js";
import { ReactDialogService } from "./views/adapter/ReactDialogService.js";
import { downloadExporter } from "./views/adapter/downloadExporter.js";
import { WorkspaceVM } from "./viewmodels/workspaceVM.js";

export function createWorkspace(repositoryOptions: InMemoryRepositoryOptions = {}): {
  workspace: WorkspaceVM;
  dialog: ReactDialogService;
} {
  // The exporter saves Export… as a browser download; without it the
  // repository serializes the workspace and discards it.
  const repo = new InMemoryNoteRepository(buildSeed(), repositoryOptions, downloadExporter);
  const dialog = new ReactDialogService();
  const workspace = WorkspaceVM.builder()
    .name("workspace")
    .hint("Notes Workspace")
    .repository(repo)
    .dialogService(dialog)
    .build();
  return { workspace, dialog };
}
