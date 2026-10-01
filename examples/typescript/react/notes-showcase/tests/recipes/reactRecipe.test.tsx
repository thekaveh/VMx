/**
 * Executable form of the React integration recipe
 * (docs/content/integration/react.md). Each docs-snippet region is shown there
 * verbatim, dedented, and `make docs-check` keeps them equal. The names the
 * recipe leaves to the application (`app`, `noteVm`, `workspace`, `screen`,
 * `EditorVM`, `Editor`, `EmptyEditor`) are defined here first.
 */
import { act, cleanup, fireEvent, render } from "@testing-library/react";
import type { JSX } from "react";
import { BehaviorSubject, Subject } from "rxjs";
import { afterAll, afterEach, describe, expect, it } from "vitest";
import {
  AsyncResourceStatus,
  AsyncResourceVM,
  ComponentVM,
  ComponentVMOf,
  CompositeVM,
  DerivedProperty,
  MessageHub,
  NullDispatcher,
  RelayCommand,
} from "@thekaveh/vmx";
import {
  useAsyncResource,
  useCommand,
  useDerivedProperty,
  useVm,
  useVmCollection,
} from "@thekaveh/vmx-react";

interface Titled {
  title: string;
}

const hub = new MessageHub();
const dispatcher = NullDispatcher.INSTANCE;

function titled(name: string, title: string): ComponentVMOf<Titled> {
  return ComponentVMOf.create<Titled>({ name, hub, dispatcher, model: { title } });
}

const appVm = titled("app", "Draft");
const app = {
  hub,
  get model(): Titled {
    return appVm.model;
  },
  busy: false,
};

let saves = 0;
const noteVm = Object.assign(titled("note", "Groceries"), {
  saveCommand: RelayCommand.builder().task(() => { saves += 1; }).build(),
});
const first = ComponentVM.create({ name: "first", hub, dispatcher });
const second = ComponentVM.create({ name: "second", hub, dispatcher });
const workspace = {
  notes: CompositeVM.create<ComponentVM>({ name: "notes", hub, dispatcher, children: () => [first, second] }),
  total: new DerivedProperty(new BehaviorSubject(3)),
};
const screen = {
  data: new AsyncResourceVM({ name: "data", loader: async () => "loaded", hub, dispatcher }),
};

type EditorVM = ComponentVMOf<Titled>;

function EmptyEditor(): JSX.Element {
  return <p>No note</p>;
}

function Editor({ title }: { title: string }): JSX.Element {
  return <h2>{title}</h2>;
}

// docs-snippet:start react-store
import { createVmxStore, shallowEqual, useVmx } from "@thekaveh/vmx-react";

const store = createVmxStore(app.hub);

function Summary() {
  const summary = useVmx(
    store,
    () => ({ title: app.model.title, busy: app.busy }),
    shallowEqual,
  );
  return <p>{summary.title}{summary.busy ? "…" : ""}</p>;
}
// docs-snippet:end react-store

function Bindings(): JSX.Element {
  // docs-snippet:start react-focused-bindings
  const title = useVm(noteVm, vm => vm.model.title);
  const save = useCommand(noteVm.saveCommand);
  const notes = useVmCollection(workspace.notes);
  const total = useDerivedProperty(workspace.total);
  const resource = useAsyncResource(screen.data);
  // docs-snippet:end react-focused-bindings
  return (
    <p>
      <span>{`${title}|${notes.length}|${String(total)}|${resource.status}`}</span>
      <button disabled={!save.canExecute} onClick={save.execute}>save</button>
    </p>
  );
}

afterEach(cleanup);
afterAll(() => {
  store.dispose();
});

describe("react recipe: shared store", () => {
  it("shows the selected application state at once and after each change", async () => {
    const view = render(<Summary />);
    expect(view.container.textContent).toBe("Draft");

    // The store coalesces a synchronous hub drain into one microtask.
    await act(async () => {
      appVm.model = { title: "Final" };
    });
    expect(view.container.textContent).toBe("Final");

    app.busy = true;
    await act(async () => {
      appVm.republishModel();
    });
    expect(view.container.textContent).toBe("Final…");
    app.busy = false;
  });
});

describe("react recipe: focused bindings", () => {
  it("renders each binding's current value, follows a model change, and runs the command", async () => {
    workspace.notes.construct();
    const view = render(<Bindings />);
    const text = (): string | null => view.container.querySelector("span")!.textContent;
    expect(text()).toBe(`Groceries|2|3|${AsyncResourceStatus.Idle}`);

    act(() => {
      noteVm.model = { title: "Errands" };
    });
    expect(text()).toBe(`Errands|2|3|${AsyncResourceStatus.Idle}`);

    await act(async () => {
      await screen.data.load();
    });
    expect(text()).toBe(`Errands|2|3|${AsyncResourceStatus.Ready}`);

    fireEvent.click(view.getByText("save"));
    expect(saves).toBe(1);
  });
});

describe("react recipe: derived property", () => {
  it("renders Loading… until the first value arrives", () => {
    // docs-snippet:start react-derived-property
    const total$ = new Subject<number>();
    const total = new DerivedProperty(total$);

    function Total() {
      const value = useDerivedProperty(total);
      return <span>{value === undefined ? "Loading…" : value}</span>;
    }
    // Renders "Loading…" until total$.next(42), then "42".
    // docs-snippet:end react-derived-property
    const view = render(<Total />);
    expect(view.container.textContent).toBe("Loading…");

    act(() => {
      total$.next(42);
    });
    expect(view.container.textContent).toBe("42");
  });
});

describe("react recipe: optional VM", () => {
  it("mounts a child that owns the binding and releases it when the VM goes away", () => {
    // docs-snippet:start react-optional-vm
    function MaybeEditor({ vm }: { vm: EditorVM | null }) {
      return vm === null ? <EmptyEditor /> : <BoundEditor vm={vm} />;
    }
    function BoundEditor({ vm }: { vm: EditorVM }) {
      const live = useVm(vm);
      return <Editor title={live.model.title} />;
    }
    // docs-snippet:end react-optional-vm
    const editor = titled("editor", "Draft");
    const view = render(<MaybeEditor vm={null} />);
    expect(view.container.textContent).toBe("No note");

    view.rerender(<MaybeEditor vm={editor} />);
    expect(view.container.textContent).toBe("Draft");

    act(() => {
      editor.model = { title: "Edited" };
    });
    expect(view.container.textContent).toBe("Edited");

    view.rerender(<MaybeEditor vm={null} />);
    act(() => {
      editor.model = { title: "After unmount" };
    });
    expect(view.container.textContent).toBe("No note");
  });
});
