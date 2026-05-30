# notes-showcase (TypeScript / React)

VMx flagship example — Notes Workspace, the TypeScript / React flavor. A
single-page web app on React 18 + Vite that drives a single `WorkspaceVM`
exercising 15 distinct VMx features (see the
[parity matrix](../../../notes-showcase-parity.md) for the full table). The
canonical scenario contract lives at
[`spec/proposals/2026-05-29-notes-showcase-scenario.md`](../../../../spec/proposals/2026-05-29-notes-showcase-scenario.md);
this README documents how the React implementation maps onto it.

The app is strictly partitioned into `src/models/`, `src/viewmodels/`,
`src/views/`. View components never call `useState` / `useReducer` —
ESLint's `no-restricted-imports` rule enforces that under
`src/views/components/**`.

## Run

```bash
cd examples/typescript/react/notes-showcase
npm install
npm run dev         # http://localhost:5173
```

Production build:

```bash
npm run build       # static bundle in dist/
```

Tests (vitest + jsdom + @testing-library/react):

```bash
npm test
npm run typecheck
```

### Temporary `node:*` shim (Phase 5.c workaround)

`vite.config.ts` registers a small `nodeBuiltinStub()` plugin that maps
`node:fs` / `node:path` / `node:url` to a Proxy module so rollup's parser is
satisfied when bundling VMx core for the browser. VMx core's
`lifecycle/transitionValidator.ts` imports those built-ins eagerly to read a
JSON fixture; the React UI never triggers that code path, but rollup would
fail at build time without the shim. The plugin is excluded under
`VITEST=true` so unit tests load the real validator from Node.

This shim is a **temporary workaround**, not a permanent design. The proper
fix is for VMx core to lazy-load the validator's fixture (or expose a
no-side-effects entry point for browser bundlers); track that as a follow-up
on the VMx TypeScript flavor — once it lands, this plugin should be removed.

## Project layout

```
examples/typescript/react/notes-showcase/
├── package.json, vite.config.ts, tsconfig.json, index.html, .eslintrc.cjs
├── src/
│   ├── main.tsx                     ← composition root
│   ├── models/
│   │   ├── notebookModel.ts, noteModel.ts
│   │   ├── noteRepository.ts        ← interface
│   │   ├── inMemoryRepository.ts, seed.ts
│   ├── viewmodels/
│   │   ├── workspaceVM.ts           ← AggregateVM6 composition
│   │   ├── notebooksRootVM.ts, notebookVM.ts
│   │   ├── notesViewVM.ts, noteVM.ts
│   │   ├── noteFormVM.ts            ← FormVM wrapper
│   │   ├── statusBarVM.ts, notificationsVM.ts
│   │   ├── capabilityActionsVM.ts, actionVM.ts
│   │   └── dialogService.ts         ← VM-side port
│   └── views/
│       ├── App.tsx, theme.css
│       ├── adapter/                 ← VMx → React bridge
│       │   ├── useVm.ts, useCommand.ts, useVmCollection.ts,
│       │   │   useDerivedProperty.ts, useDialogOverlay.ts
│       │   ├── ReactDispatcher.ts, ReactDialogService.tsx
│       │   └── _hubAccessor.ts
│       ├── components/
│       │   ├── Layout.tsx, NotebooksTree.tsx, NotesList.tsx,
│       │   │   NoteForm.tsx, StatusBar.tsx, Notifications.tsx,
│       │   │   CapabilityActions.tsx, DialogOverlay.tsx
│       │   └── modals/{ConfirmModal,SaveFileModal,NotifyModal}.tsx
│       └── hooks/useHotkeys.ts
└── tests/{models,viewmodels,views}/
```

## Feature traceability

| #   | Feature                          | Where                                                                                       |
| --- | -------------------------------- | ------------------------------------------------------------------------------------------- |
| 1   | `HierarchicalVM`                 | `viewmodels/notebooksRootVM.ts` (composes `NotebookVM` children, emits `TreeStructureChangedMessage`) |
| 2   | `CompositeVM.current`            | `viewmodels/notesViewVM.ts` (`current` two-way binding)                                     |
| 3   | `ComponentVMOf<M>` modeled       | `viewmodels/noteVM.ts`, `viewmodels/notebookVM.ts`                                          |
| 4   | `FormVM` snapshot / revert       | `viewmodels/noteFormVM.ts` (owns a strict `FormVMOf<NoteModel>`)                            |
| 5   | `DerivedProperty`                | `viewmodels/statusBarVM.ts`, `noteFormVM.isDirty`, `capabilityActionsVM.actions`             |
| 6   | `RelayCommand` reactive          | `noteFormVM.approveCommand` / `denyCommand`, `noteVM.deleteCommand`                          |
| 7   | `SearchableState` + `IFilterable`| `viewmodels/notesViewVM.ts` (debounced 150 ms search + `showStarredOnly`)                    |
| 8   | `IPageable` + `PagedComposition` | `viewmodels/notesViewVM.ts` (page size 5, paging commands delegate to inner `PagedComposition`) |
| 9   | `INotificationHub` + `NotificationVM` | `viewmodels/notificationsVM.ts`, `views/components/Notifications.tsx`                   |
| 10  | Async `construct()` + dispatcher | `viewmodels/workspaceVM.ts` (`construct()`), `views/adapter/ReactDispatcher.ts`              |
| 11  | `TreeStructureChangedMessage`    | `viewmodels/notebooksRootVM.ts` (`addNotebook` / `populate`)                                 |
| 12  | `ConfirmationDecoratorCommand`   | `viewmodels/noteVM.ts` (`deleteCommand` wraps inner delete)                                  |
| 13  | `IDialogService`                 | `viewmodels/dialogService.ts`; implemented by `views/adapter/ReactDialogService.tsx` + `views/components/modals/` |
| 14  | Capability-aware UI              | `viewmodels/capabilityActionsVM.ts` + `views/components/CapabilityActions.tsx`               |
| 15  | `AggregateVM6` (spec 2.2.0)      | `viewmodels/workspaceVM.ts` (wraps an `AggregateVM6Of<…>` of the six children)               |

## Keyboard shortcuts

| Binding         | Action                                |
| --------------- | ------------------------------------- |
| `Mod+N`         | New note in the current notebook      |
| `Mod+Shift+N`   | New notebook at the root              |
| `Mod+E`         | Export the workspace snapshot         |

`Mod` is `Cmd` on macOS, `Ctrl` elsewhere. Bindings are registered via
`useHotkeys` in `src/views/components/Layout.tsx`; each map entry calls a VM
command's `execute()` once the matching `canExecute` predicate is truthy,
keeping the Pure-VM contract intact.

## References

- Scenario contract: [`spec/proposals/2026-05-29-notes-showcase-scenario.md`](../../../../spec/proposals/2026-05-29-notes-showcase-scenario.md)
- Cross-flavor parity: [`examples/notes-showcase-parity.md`](../../../notes-showcase-parity.md)
- `AggregateVM6` rationale: [`spec/ADRs/0034-aggregate-vm6.md`](../../../../spec/ADRs/0034-aggregate-vm6.md)
