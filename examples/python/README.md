# VMx Python Examples

Five demos of the [VMx Python library](../../langs/python/).
Generated architecture diagrams for all examples live in
[`../DIAGRAMS.md`](../DIAGRAMS.md).

## 1. Setup

The console and tkinter examples share the root `examples/python` environment.
Each Textual and NiceGUI example is a standalone uv project with its own
environment and lockfile.

Run the setup, console, and tkinter commands from `examples/python`. Run the
Textual and NiceGUI commands from the repository root.

```bash
cd examples/python
uv sync          # prepares the console + tkinter environment
```

---

## 2. Example 1 — `console/hello_vmx` (console)

Minimal console demo. Demonstrates:

1. Building a `ComponentVMOf[UserModel]` with the fluent builder.
2. Subscribing to hub messages (`ConstructionStatusChangedMessage` + `PropertyChangedMessage`).
3. The full lifecycle: construct → model mutations → destruct → dispose.
4. The equality guard: setting the same model value emits **no** hub message.

Diagram:
[`python-console-hello-vmx.svg`](../../docs/assets/diagrams/python-console-hello-vmx.svg)
([HTML](../../docs/assets/diagrams/python-console-hello-vmx.html),
[PNG](../../docs/assets/diagrams/python-console-hello-vmx.png)).

**Run:**

```bash
uv run python -m hello_vmx
```

Expected output (truncated):

```
=== hello_vmx ===

Building ComponentVMOf[UserModel] ...
  vm.name   = user-vm
  vm.status = DESTRUCTED
  vm.model  = UserModel(name='Alice', age=30)

Calling construct() ...
  [hub] user-vm  status → CONSTRUCTING
  ...
  vm.is_constructed = True
  vm.modeled_hint   = 'Alice (30)'

Mutating model → Bob, 25 ...
  [hub] user-vm  property 'model' changed
  ...

Setting the SAME model value (equality guard — no hub message expected) ...

=== Done ===
```

---

## 3. Example 2 — `tk/todo_app` (tkinter MVVM)

Full MVVM todo app using tkinter. Demonstrates:

- `TodoItemVM` — subclasses `ComponentVMOf[TodoItem]`; adds a `toggle_done` `RelayCommand`.
- `MainWindowViewModel` — holds a `CompositeVM[TodoItemVM]`; exposes `add_command` and `remove_command`.
- `MainWindow` — pure view; all logic lives in the ViewModel.

Diagram:
[`python-tk-todo-app.svg`](../../docs/assets/diagrams/python-tk-todo-app.svg)
([HTML](../../docs/assets/diagrams/python-tk-todo-app.html),
[PNG](../../docs/assets/diagrams/python-tk-todo-app.png)).

**Run (requires a display):**

```bash
uv run python -m todo_app
```

**Headless import check:**

```bash
uv run python -c "from todo_app.__main__ import MainWindow; print('OK')"
```

**Host check:** runs the window on a real Tk root. It types, adds, toggles and
removes items through the widgets, then closes the window and checks that every
subscription is disposed and nothing keeps the view-model alive. CI runs it
under Xvfb:

```bash
xvfb-run --auto-servernum uv run python -m todo_app.host_check
```

---

## 4. Example 3 — `textual/inspector` (Textual TUI)

A general-purpose live inspector for any VMx hierarchy. Demonstrates:

- `vmx.tree.walk` driving a `textual.widgets.Tree` view of the VM hierarchy.
- A `DataTable` log subscribed to `hub.messages`, showing every
  `PropertyChangedMessage` and `ConstructionStatusChangedMessage` as it fires.
- Lifecycle keybindings (`c` construct, `d` destruct, `r` reconstruct,
  `x` dispose, `s` select) on the highlighted node.

Diagram:
[`python-textual-inspector.svg`](../../docs/assets/diagrams/python-textual-inspector.svg)
([HTML](../../docs/assets/diagrams/python-textual-inspector.html),
[PNG](../../docs/assets/diagrams/python-textual-inspector.png)).

`textual/inspector/` is its own uv project because Textual is a heavier
dependency than the console and tkinter examples. Run it from the repository
root:

```bash
uv run --project examples/python/textual/inspector python -m vmx_inspector
```

---

## 5. Example 4 — `textual/notes_showcase` (Textual TUI, flagship)

The Notes Workspace flagship app is a TUI on Textual ≥ 0.80 that exercises
19 VMx features in one scenario. The
[parity matrix](../notes-showcase-parity.md) lists them. Widget classes expose
only `compose()`, `on_mount()`, and one-statement `action_*()` methods.

Diagram:
[`python-textual-notes-showcase.svg`](../../docs/assets/diagrams/python-textual-notes-showcase.svg)
([HTML](../../docs/assets/diagrams/python-textual-notes-showcase.html),
[PNG](../../docs/assets/diagrams/python-textual-notes-showcase.png)).

`textual/notes_showcase/` is its own uv project. Run it from the repository
root:

```bash
uv run --project examples/python/textual/notes_showcase python -m notes_showcase
```

See [`textual/notes_showcase/README.md`](textual/notes_showcase/README.md)
for project layout, feature traceability, and keybindings (`Ctrl+S` to save,
`Ctrl+F` to search, and others). The canonical scenario contract is at
[`../../spec/proposals/2026-05-29-notes-showcase-scenario.md`](../../spec/proposals/2026-05-29-notes-showcase-scenario.md).

---

## 6. Example 5 — `nicegui/notes_showcase` (NiceGUI web page)

A NiceGUI web page over the same workspace view-models as the Textual
flagship. It reuses that project's models and view-models; only the host, the
page, and a small adapter live here. It is its own uv project. Start from
the repository root:

```bash
cd examples/python/nicegui/notes_showcase
uv sync --locked
uv run python -m nicegui_notes
```

Then open <http://localhost:8080>. See
[`nicegui/notes_showcase/README.md`](nicegui/notes_showcase/README.md) for the
layout and checks.

---

## 7. Project layout

```
examples/python/
├── pyproject.toml              # shared deps (vmx local path via uv.sources)
├── README.md                   # this file
├── console/
│   └── hello_vmx/
│       ├── __init__.py
│       └── __main__.py         # entry point: python -m hello_vmx
├── tk/
│   ├── todo_app/
│   │   ├── __init__.py
│   │   ├── __main__.py         # entry point: python -m todo_app
│   │   └── host_check.py       # CI host check: python -m todo_app.host_check
│   └── note_recipe/            # tkinter recipe checked in CI: python -m note_recipe
├── nicegui/
│   └── notes_showcase/         # stand-alone uv project (NiceGUI web page)
└── textual/
    ├── inspector/              # stand-alone uv project (Textual)
    │   ├── pyproject.toml
    │   ├── README.md
    │   ├── src/vmx_inspector/
    │   └── tests/
    └── notes_showcase/         # stand-alone uv project (Textual flagship)
        ├── pyproject.toml
        ├── README.md
        ├── src/notes_showcase/
        └── tests/
```
