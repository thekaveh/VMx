/**
 * The notebook UI. React renders VM state through `@thekaveh/vmx-react`:
 *
 * - `createVmxStore(hub)` adapts the hub to React's external-store protocol.
 * - `useVmx(store, selector)` selects what each component renders.
 * - `useCommand(command)` tracks `canExecute` for the Save button.
 *
 * `NotebookHost` creates the VMs in an effect and disposes them in its
 * cleanup, so the flow is safe under StrictMode's mount, unmount, remount.
 */
import { useEffect, useState } from "react";

import { ConstructionStatus, __version__ } from "@thekaveh/vmx";
import {
  createVmxStore,
  shallowEqual,
  useCommand,
  useVmx,
  type VmxStore,
} from "@thekaveh/vmx-react";

import { InMemoryNoteStore, NoteConflictError, NotebookApp, type NoteModel } from "./notes";

const SEED: readonly NoteModel[] = [
  { id: "1", title: "Groceries", body: "Milk, eggs" },
  { id: "2", title: "Ideas", body: "Write a starter" },
];

interface Session {
  readonly app: NotebookApp;
  readonly store: VmxStore;
  readonly notes: InMemoryNoteStore;
}

export function App() {
  const [open, setOpen] = useState(true);
  const [lifecycle, setLifecycle] = useState("not started");

  return (
    <main>
      <h1>VMx React starter</h1>
      <p>
        VMx <span data-testid="vmx-version">{__version__}</span>
        {" · "}lifecycle <output data-testid="lifecycle">{lifecycle}</output>
      </p>
      <button type="button" onClick={() => setOpen((value) => !value)}>
        {open ? "Close notebook" : "Open notebook"}
      </button>
      {open ? <NotebookHost onLifecycle={setLifecycle} /> : null}
    </main>
  );
}

function NotebookHost({ onLifecycle }: { onLifecycle: (state: string) => void }) {
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    const notes = new InMemoryNoteStore();
    const app = new NotebookApp(notes, SEED);
    app.start();
    const store = createVmxStore(app.hub);
    setSession({ app, store, notes });
    onLifecycle(app.notebook.isConstructed ? "constructed" : "not constructed");
    return () => {
      // Dispose the React store first, then the VMs and the hub.
      store.dispose();
      app.dispose();
      onLifecycle(app.notebook.status === ConstructionStatus.Disposed ? "disposed" : "leaked");
    };
  }, [onLifecycle]);

  return session === null ? <p>Loading…</p> : <Notebook session={session} />;
}

function Notebook({ session }: { session: Session }) {
  const { app, store, notes } = session;
  const view = useVmx(
    store,
    () => ({
      currentId: app.notebook.current?.model.id ?? "",
      title: app.notebook.current?.model.title ?? "",
      hint: app.notebook.current?.modeledHint ?? "",
      ids: [...app.notebook].map((note) => note.model.id).join(","),
    }),
    shallowEqual,
  );
  const save = useCommand(app.saveCurrent);
  const [saved, setSaved] = useState<readonly string[]>([]);
  const [error, setError] = useState("");

  const onSave = async () => {
    setError("");
    try {
      await app.saveCurrent.executeAsync();
      setSaved(SEED.map((seed) => notes.get(seed.id)?.title).filter((t) => t !== undefined));
    } catch (failure) {
      // Error path: the store rejects a duplicate title; the app keeps running.
      if (!(failure instanceof NoteConflictError)) throw failure;
      setError(failure.message);
    }
  };

  return (
    <section>
      <nav>
        {view.ids.split(",").map((id) => (
          <button
            key={id}
            type="button"
            data-testid={`select-${id}`}
            aria-pressed={id === view.currentId}
            onClick={() => app.select(id)}
          >
            Note {id}
          </button>
        ))}
      </nav>
      <TitleEditor
        key={view.currentId}
        initial={view.title}
        onChange={(title) => app.renameCurrent(title)}
      />
      <p>
        Current: <output data-testid="hint">{view.hint}</output>
      </p>
      <button type="button" disabled={!save.canExecute} onClick={() => void onSave()}>
        Save
      </button>
      <p role="alert" data-testid="error">
        {error}
      </p>
      <p>
        Saved: <output data-testid="saved">{saved.join(", ")}</output>
      </p>
    </section>
  );
}

/** Keeps a local draft so typing never fights the asynchronous store update. */
function TitleEditor({ initial, onChange }: { initial: string; onChange: (title: string) => void }) {
  const [draft, setDraft] = useState(initial);
  return (
    <label>
      Title{" "}
      <input
        data-testid="title"
        value={draft}
        onChange={(event) => {
          setDraft(event.target.value);
          onChange(event.target.value);
        }}
      />
    </label>
  );
}
