# 9.5. Textual Integration

Wire a `ComponentVMOf[M]` to a [Textual](https://textual.textualize.io/)
TUI widget through Textual's `reactive` descriptors.

## 9.5.1. Reactivity primitive

Textual widgets re-render when a `reactive(...)` attribute changes. A VMx VM
reports its own changes on `property_changed`, an observable of snake_case
property names: a setter such as `model` publishes a `PropertyChangedMessage`
to the hub and then emits its name there, and every lifecycle transition
publishes a `ConstructionStatusChangedMessage` and then emits `status`. The hub
never carries a `PropertyChangedMessage` for `status`.

## 9.5.2. Mapping

| Textual                | VMx                                                |
| ---------------------- | -------------------------------------------------- |
| `reactive("value")`    | `vm.property_changed` (VM-local names)             |
| `Binding` + `action_*` | `RelayCommand.execute()`                           |
| `ListView` items       | `ObservableList[T]` + `CollectionChangedMessage`   |
| `post_message`         | thread-safe hand-off of a change to the App thread |

## 9.5.3. Adapter skeleton

The widget below is the exact module that the Textual Notes-Showcase tests run
on a live App (`examples/python/textual/notes_showcase/tests/views/`), including
a change made on a worker thread.

<!-- checked-snippet: examples/python/textual/notes_showcase/tests/views/textual_recipe.py -->

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from reactivex.abc import DisposableBase
from textual.app import RenderResult
from textual.binding import Binding, BindingType
from textual.message import Message as TextualMessage
from textual.reactive import reactive
from textual.widget import Widget
from vmx import ComponentVMOf, RelayCommand


@dataclass
class Note:
    title: str


class NoteWidget(Widget, can_focus=True):
    """Shows a borrowed note VM; whoever created the VM constructs and disposes it."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("s", "save", "Save")]

    title: reactive[str] = reactive("")
    status_text: reactive[str] = reactive("")

    class VmChanged(TextualMessage):
        """Carries one VM-local property change onto the App thread."""

        def __init__(self, property_name: str) -> None:
            super().__init__()
            self.property_name = property_name

    def __init__(self, vm: ComponentVMOf[Note], save_command: RelayCommand) -> None:
        super().__init__()
        self._vm = vm
        self._save_command = save_command
        self._subscription: DisposableBase | None = None

    def on_mount(self) -> None:
        # `property_changed` is the VM-local stream: it carries `model`
        # assignments and every lifecycle `status` change, on the thread that
        # made the change. `post_message` is thread-safe and queues each change
        # for this widget on the App thread.
        self._subscription = self._vm.property_changed.subscribe(self._forward)
        # Read after subscribing, so a change in between is not lost.
        self._show("model")
        self._show("status")

    def _forward(self, property_name: str) -> None:
        self.post_message(self.VmChanged(property_name))

    def on_note_widget_vm_changed(self, message: NoteWidget.VmChanged) -> None:
        self._show(message.property_name)

    def _show(self, property_name: str) -> None:
        if property_name == "model":
            self.title = self._vm.model.title
        elif property_name == "status":
            self.status_text = self._vm.status.name

    def render(self) -> RenderResult:
        return f"{self.title} · {self.status_text}"

    def action_save(self) -> None:
        self._save_command.execute(None)

    def on_unmount(self) -> None:
        if self._subscription is not None:
            self._subscription.dispose()
            self._subscription = None
```

- **One notification path.** Subscribe to `property_changed` only. Also
  handling the hub's `PropertyChangedMessage` notifies `model` twice, and the
  hub never carries `status`.
- **Current values at once.** `on_mount` subscribes, then reads the VM, so the
  first render shows the current title and status and a change made in between
  is not lost.
- **App thread only.** `property_changed` emits on the thread that made the
  change. `post_message` is thread-safe, so the widget reads the VM and assigns
  its reactive attributes only on the App thread. Each handled message shows
  the VM's current value, so a transient status such as `CONSTRUCTING` may be
  skipped when it is already over.
- **Borrowed lifetime.** `on_unmount` disposes the subscription and nothing
  else. The code that created the VM constructs and disposes it.

A host that runs VMx work on its own threads owns that machinery:
`TextualDispatcher` captures the running App loop and uses
`AsyncIOThreadSafeScheduler(loop)` for worker-to-loop delivery. The host must
stop admissions, await admitted hooks while the loop remains responsive,
dispose resources, then explicitly release any `ThreadPoolScheduler` it
created; use the shared
[Python asyncio dispatcher ownership](../primitives/services-messages-dispatching.md#669-python-asyncio-dispatcher-ownership)
teardown sequence.

## 9.5.4. Fuller example

- [`examples/python/textual/inspector/`](../../../examples/python/textual/inspector/) —
  a Textual viewer for any VMx tree, demonstrating the hub-subscription
  pattern at scale.
- [`examples/python/textual/notes_showcase/`](../../../examples/python/textual/notes_showcase/) —
  the Notes-Showcase Textual flagship: full `WorkspaceVM` with
  `bind_property` / `bind_command` helpers (shipped in v2.2.0; ThemeVM
  added in v2.4.0).
