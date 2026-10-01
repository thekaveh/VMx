# 9.6. NiceGUI Integration

[NiceGUI](https://nicegui.io/) is a Python web framework that exposes
declarative UI components. Wire a `ComponentVMOf[M]` by subscribing to
the VMx hub and calling `element.update()` (or rebinding `.text`,
`.value`, etc.) on property changes.

## 9.6.1. Reactivity primitive

NiceGUI elements expose mutable `.text`, `.value`, `.props`, and similar
attributes. Pushing a new value followed by `element.update()` re-renders
the element. There is no built-in observable model.

## 9.6.2. Mapping

| NiceGUI                             | VMx                                                               |
| ----------------------------------- | ----------------------------------------------------------------- |
| `ui.label('x').bind_text_from(...)` | subscribe + assign in handler                                     |
| `ui.button(on_click=fn)`            | `command.execute(None)` inside `on_click`                         |
| `ui.refreshable`-decorated builder  | re-build when `CollectionChangedMessage` fires                    |
| `app.add_timer` / `asyncio` loop    | `RxDispatcher.asyncio(loop)` → `AsyncIOThreadSafeScheduler(loop)` |

## 9.6.3. Adapter skeleton

**Illustrative, not checked.** NiceGUI is not a dependency of this repository,
so CI does not compile or run the fences on this page, unlike the recipes listed
in [How The Recipes Are Checked](index.md#916-how-the-recipes-are-checked).
Check them against the NiceGUI version your application pins.

Capture the loop inside NiceGUI's running async host callback; do not create an
unrelated loop during module import or close the host's loop. The foreground
channel is `AsyncIOThreadSafeScheduler(loop)`, while rendering context remains
host-owned:

```python
import asyncio

from nicegui import app
from vmx.services import RxDispatcher


@app.on_startup
async def configure_vmx() -> None:
    dispatcher = RxDispatcher.asyncio(asyncio.get_running_loop())
    # Retain dispatcher with the host; dispose and clean up on shutdown.
```

On shutdown, stop submissions, await admitted hooks while the host loop remains
responsive, dispose host-owned VMs and subscriptions, then explicitly clean up
the independent pool as shown in [Python asyncio dispatcher
ownership](../primitives/services-messages-dispatching.md#669-python-asyncio-dispatcher-ownership).

The direct subscription below requires every matching `PropertyChangedMessage`
to arrive on NiceGUI's UI loop and within the current client's rendering
context. Background lifecycle terminal messages have that foreground delivery;
foreign producers must use a host bridge or foreground observation before they
touch an element.

```python
from collections.abc import Callable

from nicegui import ui
import reactivex.operators as ops
from vmx import ComponentVMOf, Message, MessageHubProto, PropertyChangedMessage, RelayCommand

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

# Page builder (runs in NiceGUI's host-owned rendering context):
def render(vm: ComponentVMOf[Note], hub: MessageHubProto[Message],
           save_command: RelayCommand) -> None:
    label = ui.label()
    dispose = bind_label(label, vm, hub)
    ui.button("Save", on_click=lambda: save_command.execute(None))
    ui.context.client.on_disconnect(dispose)
```

## 9.6.4. Fuller example

No worked NiceGUI Notes-Showcase ships yet. The Textual recipe
([textual.md](textual.md)) uses the same hub-subscription shape and is a
good reference.
