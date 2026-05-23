# VMx Python Examples

Two self-contained demos of the [VMx Python library](../../langs/python/).

## Setup

All examples share a single virtual environment managed by [uv](https://docs.astral.sh/uv/).

```bash
cd examples/python
uv sync          # creates .venv and installs vmx (editable) + reactivex
```

---

## Example 1 — `hello_vmx` (console)

Minimal console demo. Demonstrates:

1. Building a `ComponentVMOf[UserModel]` with the fluent builder.
2. Subscribing to hub messages (`ConstructionStatusChangedMessage` + `PropertyChangedMessage`).
3. The full lifecycle: construct → model mutations → destruct → dispose.
4. The equality guard: setting the same model value emits **no** hub message.

**Run:**

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

## Example 2 — `tk_todo_app` (tkinter MVVM)

Full MVVM todo app using tkinter. Demonstrates:

- `TodoItemVM` — subclasses `ComponentVMOf[TodoItem]`; adds a `toggle_done` `RelayCommand`.
- `MainWindowViewModel` — holds a `CompositeVM[TodoItemVM]`; exposes `add_command` and `remove_command`.
- `MainWindow` — pure view; all logic lives in the ViewModel.

**Run (requires a display):**

```bash
cd examples/python
uv run python -m tk_todo_app
```

**Headless import check:**

```bash
cd examples/python
uv run python -c "from tk_todo_app.__main__ import MainWindow; print('OK')"
```

---

## Project layout

```
examples/python/
├── pyproject.toml          # shared deps (vmx local path via uv.sources)
├── README.md               # this file
├── hello_vmx/
│   ├── __init__.py
│   └── __main__.py         # entry point: python -m hello_vmx
└── tk_todo_app/
    ├── __init__.py
    └── __main__.py         # entry point: python -m tk_todo_app
```
