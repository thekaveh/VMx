# VMx Python Examples

Four self-contained demos of the [VMx Python library](../../langs/python/).
Generated architecture diagrams for all examples live in
[`../DIAGRAMS.md`](../DIAGRAMS.md).

## 1. Setup

All examples share a single virtual environment managed by [uv](https://docs.astral.sh/uv/).

```bash
cd examples/python
uv sync          # creates .venv and installs vmx (editable) + reactivex
```

---

## 2. Example 1 — `console/hello_vmx` (console)

Minimal console demo. Demonstrates:

1. Building a `ComponentVMOf[UserModel]` with the fluent builder.
2. Subscribing to hub messages (`ConstructionStatusChangedMessage` + `PropertyChangedMessage`).
3. The full lifecycle: construct → model mutations → destruct → dispose.
4. The equality guard: setting the same model value emits **no** hub message.

**Run:**

Diagram:
[`python-console-hello-vmx.svg`](../../docs/assets/diagrams/python-console-hello-vmx.svg)
([HTML](../../docs/assets/diagrams/python-console-hello-vmx.html),
[PNG](../../docs/assets/diagrams/python-console-hello-vmx.png)).

```bash
cd examples/python
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

**Run (requires a display):**

Diagram:
[`python-tk-todo-app.svg`](../../docs/assets/diagrams/python-tk-todo-app.svg)
([HTML](../../docs/assets/diagrams/python-tk-todo-app.html),
[PNG](../../docs/assets/diagrams/python-tk-todo-app.png)).

```bash
cd examples/python
uv run python -m todo_app
```

**Headless import check:**

```bash
cd examples/python
uv run python -c "from todo_app.__main__ import MainWindow; print('OK')"
```

---

## 4. Example 3 — `textual/inspector` (Textual TUI)

A general-purpose live inspector for any VMx hierarchy. Demonstrates:

- `vmx.tree.walk` driving a `textual.widgets.Tree` view of the VM hierarchy.
- A `DataTable` log subscribed to `hub.messages`, showing every
  `PropertyChangedMessage` and `ConstructionStatusChangedMessage` as it fires.
- Lifecycle keybindings (`c` construct, `d` destruct, `r` reconstruct,
  `x` dispose, `s` select) on the highlighted node.

`textual/inspector/` is its own uv project (Textual is a heavier dependency
than the other two examples) — run it from its own directory:

Diagram:
[`python-textual-inspector.svg`](../../docs/assets/diagrams/python-textual-inspector.svg)
([HTML](../../docs/assets/diagrams/python-textual-inspector.html),
[PNG](../../docs/assets/diagrams/python-textual-inspector.png)).

```bash
uv run --project examples/python/textual/inspector python -m vmx_inspector
```

---

## 5. Example 4 — `textual/notes_showcase` (Textual TUI, flagship)

The Notes Workspace flagship app — a TUI on Textual ≥ 0.80 that exercises
**19 distinct VMx features** in one cohesive scenario (notebooks tree,
paged + filterable notes list, FormVM editor, capability-aware action bar,
notifications, async lifecycle, dialogs, `AggregateVM6` root, and the
v2.4.0 `ThemeVM` scenario contract, plus token-paged global search,
edit/preview state, and tag autocomplete). Pure-VM contract enforced; widget
classes expose only `compose()` / `on_mount()` / one-statement `action_*()`.

`textual/notes_showcase/` is its own uv project — run it from the repo root:

Diagram:
[`python-textual-notes-showcase.svg`](../../docs/assets/diagrams/python-textual-notes-showcase.svg)
([HTML](../../docs/assets/diagrams/python-textual-notes-showcase.html),
[PNG](../../docs/assets/diagrams/python-textual-notes-showcase.png)).

```bash
uv run --project examples/python/textual/notes_showcase python -m notes_showcase
```

See [`textual/notes_showcase/README.md`](textual/notes_showcase/README.md)
for project layout, feature-traceability, and keybindings (`Ctrl+S` to save,
`Ctrl+F` to search, etc.). Cross-flavor parity is documented in
[`../notes-showcase-parity.md`](../notes-showcase-parity.md); the canonical
scenario contract lives at
[`../../spec/proposals/2026-05-29-notes-showcase-scenario.md`](../../spec/proposals/2026-05-29-notes-showcase-scenario.md).

---

## 6. Project layout

```
examples/python/
├── pyproject.toml              # shared deps (vmx local path via uv.sources)
├── README.md                   # this file
├── console/
│   └── hello_vmx/
│       ├── __init__.py
│       └── __main__.py         # entry point: python -m hello_vmx
├── tk/
│   └── todo_app/
│       ├── __init__.py
│       └── __main__.py         # entry point: python -m todo_app
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
