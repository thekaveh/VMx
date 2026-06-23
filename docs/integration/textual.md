# Textual integration

Wire a `ComponentVMOf[M]` to a [Textual](https://textual.textualize.io/)
TUI widget through Textual's `reactive` descriptors.

## 1. Reactivity primitive

Textual widgets re-render when a `reactive(...)` attribute changes.
VMx VMs publish `PropertyChangedMessage[T]` to their `MessageHub`. The
adapter subscribes to the hub and forwards changes into the widget's
reactive attributes.

## 2. Mapping

| Textual                | VMx                                              |
| ---------------------- | ------------------------------------------------ |
| `reactive("value")`    | `PropertyChangedMessage[T]` on `MessageHub`      |
| `Button.action_press`  | `RelayCommand.execute()`                         |
| `ListView` items       | `ObservableList[T]` + `CollectionChangedMessage` |
| `App.call_from_thread` | `RxDispatcher.asyncio(loop).foreground`          |

## 3. Adapter skeleton

```python
from textual.widget import Widget
from textual.reactive import reactive
import reactivex.operators as ops

class BindableWidget(Widget):
    title: reactive[str] = reactive("")
    status_text: reactive[str] = reactive("")

    def __init__(self, vm: ComponentVMOf[Note], hub: MessageHubProto[Message]):
        super().__init__()
        self._vm = vm
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
`self._vm.save_command.execute(None)`.

## 4. Fuller example

- [`examples/python/textual/inspector/`](../../examples/python/textual/inspector/) —
  a Textual viewer for any VMx tree, demonstrating the hub-subscription
  pattern at scale.
- [`examples/python/textual/notes_showcase/`](../../examples/python/textual/notes_showcase/) —
  the Notes-Showcase Textual flagship: full `WorkspaceVM` with
  `bind_property` / `bind_command` helpers (shipped in v2.2.0; ThemeVM
  added in v2.4.0).
