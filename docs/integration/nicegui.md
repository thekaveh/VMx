# NiceGUI integration

[NiceGUI](https://nicegui.io/) is a Python web framework that exposes
declarative UI components. Wire a `ComponentVMOf[M]` by subscribing to
the VMx hub and calling `element.update()` (or rebinding `.text`,
`.value`, etc.) on property changes.

## 1. Reactivity primitive

NiceGUI elements expose mutable `.text`, `.value`, `.props`, and similar
attributes. Pushing a new value followed by `element.update()` re-renders
the element. There is no built-in observable model.

## 2. Mapping

| NiceGUI                             | VMx                                            |
| ----------------------------------- | ---------------------------------------------- |
| `ui.label('x').bind_text_from(...)` | subscribe + assign in handler                  |
| `ui.button(on_click=fn)`            | `command.execute(None)` inside `on_click`      |
| `ui.refreshable`-decorated builder  | re-build when `CollectionChangedMessage` fires |
| `app.add_timer` / `asyncio` loop    | `RxDispatcher.asyncio(loop)`                   |

## 3. Adapter skeleton

```python
from collections.abc import Callable

from nicegui import ui
import reactivex.operators as ops
from vmx import ComponentVMOf, Message, MessageHubProto, PropertyChangedMessage

def bind_label(label: ui.label, vm: ComponentVMOf[Note],
               hub: MessageHubProto[Message]) -> Callable[[], None]:
    label.text = vm.model.title

    def _on_msg(msg: PropertyChangedMessage[object]) -> None:
        if msg.property_name == "model":
            label.text = vm.model.title
            label.update()

    sub = hub.messages.pipe(
        ops.filter(lambda m: isinstance(m, PropertyChangedMessage) and m.sender is vm),
    ).subscribe(_on_msg)
    return sub.dispose  # call on page teardown

# Page builder:
def render(vm: ComponentVMOf[Note], hub: MessageHubProto[Message]) -> None:
    label = ui.label()
    dispose = bind_label(label, vm, hub)
    ui.button("Save", on_click=lambda: vm.save_command.execute(None))
    ui.context.client.on_disconnect(dispose)
```

## 4. Fuller example

No worked NiceGUI Notes-Showcase ships yet. The Textual recipe
([textual.md](textual.md)) uses the same hub-subscription shape and is a
good reference.
