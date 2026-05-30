# Textual integration

Wire a `ComponentVMOf[M]` to a [Textual](https://textual.textualize.io/)
TUI widget through Textual's `reactive` descriptors.

## Reactivity primitive

Textual widgets re-render when a `reactive(...)` attribute changes.
VMx VMs publish `PropertyChangedMessage[T]` to their `MessageHub`. The
adapter subscribes to the hub and forwards changes into the widget's
reactive attributes.

## Mapping

| Textual                | VMx                                              |
| ---------------------- | ------------------------------------------------ |
| `reactive("value")`    | `PropertyChangedMessage[T]` on `MessageHub`      |
| `Button.action_press`  | `RelayCommand.execute()`                         |
| `ListView` items       | `ObservableList[T]` + `CollectionChangedMessage` |
| `App.call_from_thread` | `RxDispatcher.asyncio(loop).foreground`          |

## Adapter skeleton

```python
from textual.widget import Widget
from textual.reactive import reactive

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

## Fuller example

- [`examples/python/vmx_inspector/`](../../examples/python/vmx_inspector/) —
  a Textual viewer for any VMx tree, demonstrating the hub-subscription
  pattern at scale.
- Notes-Showcase Textual app — full WorkspaceVM with `bind_property` /
  `bind_command` helpers. Lands in **v2.2.0** via the
  `examples-notes-showcase` branch.
