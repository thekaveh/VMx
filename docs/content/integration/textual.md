# 9.5. Textual Integration

Wire a `ComponentVMOf[M]` to a [Textual](https://textual.textualize.io/)
TUI widget through Textual's `reactive` descriptors.

## 9.5.1. Reactivity primitive

Textual widgets re-render when a `reactive(...)` attribute changes.
VMx VMs publish `PropertyChangedMessage[T]` to their `MessageHub`. The
adapter subscribes to the hub and forwards changes into the widget's
reactive attributes.

## 9.5.2. Mapping

| Textual               | VMx                                                        |
| --------------------- | ---------------------------------------------------------- |
| `reactive("value")`   | `PropertyChangedMessage[T]` on `MessageHub`                |
| `Button.action_press` | `RelayCommand.execute()`                                   |
| `ListView` items      | `ObservableList[T]` + `CollectionChangedMessage`           |
| background worker     | `AsyncIOThreadSafeScheduler(App loop)` foreground delivery |

## 9.5.3. Adapter skeleton

`TextualDispatcher` captures the running App loop and uses
`AsyncIOThreadSafeScheduler(loop)` for worker-to-loop delivery. Textual's
`post_message` remains the host bridge for foreign producers; do not call
`App.call_from_thread` from the App thread. The host owns the App loop and must
stop admissions, await admitted hooks while that loop remains responsive,
dispose resources, then explicitly release any `ThreadPoolScheduler` it
created; use the shared
[Python asyncio dispatcher ownership](../primitives/services-messages-dispatching.md#669-python-asyncio-dispatcher-ownership)
teardown sequence.

The direct subscription below requires every matching `PropertyChangedMessage`
to arrive on the App thread. Background lifecycle terminal messages have that
foreground delivery, but arbitrary foreign property producers do not. Route
those through `post_message` or observe them on the foreground scheduler before
touching a widget.

```python
from textual.widget import Widget
from textual.reactive import reactive
import reactivex.operators as ops
from vmx import ComponentVMOf, Message, MessageHubProto, PropertyChangedMessage, RelayCommand

class BindableWidget(Widget):
    title: reactive[str] = reactive("")
    status_text: reactive[str] = reactive("")

    def __init__(self, vm: ComponentVMOf[Note], hub: MessageHubProto[Message],
                 save_command: RelayCommand):
        super().__init__()
        self._vm = vm
        self._save_command = save_command
        self._sub = hub.messages.pipe(
            ops.filter(lambda m: isinstance(m, PropertyChangedMessage)
                                 and m.sender is vm),
        ).subscribe(self._on_property_changed)

    def _on_property_changed(self, msg: PropertyChangedMessage[object]) -> None:
        if msg.property_name == "model":
            self.title = self._vm.model.title
        elif msg.property_name == "status":
            self.status_text = str(self._vm.status)

    def on_unmount(self) -> None:
        self._sub.dispose()
```

For buttons: bind the widget's `action_*` handler to call
`self._save_command.execute(None)`.

## 9.5.4. Fuller example

- [`examples/python/textual/inspector/`](../../../examples/python/textual/inspector/) —
  a Textual viewer for any VMx tree, demonstrating the hub-subscription
  pattern at scale.
- [`examples/python/textual/notes_showcase/`](../../../examples/python/textual/notes_showcase/) —
  the Notes-Showcase Textual flagship: full `WorkspaceVM` with
  `bind_property` / `bind_command` helpers (shipped in v2.2.0; ThemeVM
  added in v2.4.0).
