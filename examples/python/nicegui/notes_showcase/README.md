# NiceGUI Notes-Showcase

A NiceGUI web page over the same workspace view-models as the
[Textual Notes-Showcase](../../textual/notes_showcase/). It reuses that
project's models and view-models and duplicates none of them; only the host,
the page, and a small adapter live here.

## 1. Run

```bash
cd examples/python/nicegui/notes_showcase
uv sync --locked
uv run python -m nicegui_notes
```

Then open <http://localhost:8080>. Every browser tab binds to the same
workspace, like a desktop app opened twice.

## 2. Layout

| Path                         | What it holds                                                                 |
| ---------------------------- | ----------------------------------------------------------------------------- |
| `src/nicegui_notes/adapter/` | Bindings from VMx view-models to NiceGUI elements, applied on the loop, per page |
| `src/nicegui_notes/host.py`  | The composition root: builds the workspace at startup, tears it down at shutdown |
| `src/nicegui_notes/page.py`  | The page: notebooks, the note list, and the editor                              |
| `tests/`                     | Bridge, lifetime, and smoke tests in NiceGUI's user simulation                  |

## 3. Check

Run from `examples/python/nicegui/notes_showcase`:

```bash
uv run ruff check
uv run ruff format --check
uv run mypy --strict src
uv run pytest
```

CI runs the same commands in the python workflow's `examples (nicegui)` job.
The method and the lifetime rules are in
[NiceGUI Integration](../../../../docs/content/integration/nicegui.md).
