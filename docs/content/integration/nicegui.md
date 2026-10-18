# 9.6. NiceGUI Integration

[NiceGUI](https://nicegui.io/) is a Python web framework: the server builds each
browser page from Python and pushes element updates over a socket. The
NiceGUI Notes-Showcase
([`examples/python/nicegui/notes_showcase/`](../../../examples/python/nicegui/notes_showcase/))
binds the same workspace view-models as the Textual Notes-Showcase through a
small in-example adapter. The python `examples (nicegui)` job runs its tests in
NiceGUI's user simulation, and every fence on this page is a region of that
example that `make docs-check` compares with the source.

## 9.6.1. Reactivity primitive

NiceGUI elements have bindable properties. `bind_text_from` and its siblings
follow a `BindableProperty` or `bindable_dataclass` attribute directly and fall
back to a polling refresh loop for plain attributes. VMx view-models already
publish each change on their hub, so the adapter subscribes there and pushes the
change into the element: nothing polls, and the view-model stays the only
source of the value.

## 9.6.2. Mapping

| NiceGUI                                       | VMx                                                             |
| --------------------------------------------- | --------------------------------------------------------------- |
| element attribute (`label.text`, …)           | `bind_property`: a hub `PropertyChangedMessage` re-reads the VM |
| `ui.input` value + `on_value_change`          | `bind_property_two_way`, without echoes                         |
| `ui.button(on_click=…)` + `set_enabled`       | `bind_command`: `execute()`, enabled follows `can_execute()`    |
| page-local `@ui.refreshable` builder          | `bind_refreshable` on a collection's change stream              |
| `app.on_startup` (async handlers not awaited) | capture the running loop: `RxDispatcher.asyncio(loop)`          |
| `client.on_delete`                            | release the page's bindings                                     |
| `app.on_shutdown` (awaited)                   | release pages, dispose the VMs, shut down the dispatcher pool   |

## 9.6.3. Adapter skeleton

A VMx view-model publishes a change on the thread that made it. A NiceGUI
element must be touched on the server's event loop, inside the client (browser
page) that owns it. Each binding captures that loop and client when the page is
built, and applies every later change through them:

<!-- checked-snippet: examples/python/nicegui/notes_showcase/src/nicegui_notes/adapter/delivery.py#nicegui-delivery -->

```python
class ClientDelivery:
    """Captured inside a page builder: the running loop, its thread, and the page's client."""

    def __init__(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._thread = threading.get_ident()
        self._client: Client = ui.context.client

    @property
    def client(self) -> Client:
        return self._client

    def run(self, update: Callable[[], None]) -> None:
        """Apply ``update`` now on the loop thread, or schedule it there from any other thread."""
        if threading.get_ident() == self._thread:
            self._apply(update)
            return
        try:
            self._loop.call_soon_threadsafe(self._apply, update)
        except RuntimeError:
            pass  # the server's loop has closed; there is no page left to update

    def _apply(self, update: Callable[[], None]) -> None:
        if self._client.is_deleted:
            return
        with self._client:
            update()
```

A one-way binding seeds the element, then re-reads the view-model on each
matching hub message:

<!-- checked-snippet: examples/python/nicegui/notes_showcase/src/nicegui_notes/adapter/binding.py#nicegui-bind-property -->

```python
def bind_property(
    element: Element,
    attr: str,
    vm: Any,
    vm_property: str,
    transform: Callable[[Any], object] | None = None,
) -> DisposableBase:
    """One-way: ``vm.<vm_property>`` → ``element.<attr>``, optionally transformed."""
    delivery = ClientDelivery()

    def _show() -> None:
        value = getattr(vm, vm_property)
        setattr(element, attr, transform(value) if transform is not None else value)

    _show()
    return vm_property_changes(vm, {vm_property}).subscribe(on_next=lambda _: delivery.run(_show))
```

`bind_property_two_way`, `bind_derived_property`, `bind_command`, and
`bind_refreshable` follow the same shape in
[`adapter/binding.py`](../../../examples/python/nicegui/notes_showcase/src/nicegui_notes/adapter/binding.py).
A cleared `ui.input` reports `None`, so text fields pass `text` as the two-way
binding's parser before the value reaches a `str` property.

A page releases its bindings when NiceGUI deletes its client. Since NiceGUI 3.0,
`client.on_disconnect` also fires when a browser reconnects, so releasing there
would leave a page without bindings after a brief network drop:

<!-- checked-snippet: examples/python/nicegui/notes_showcase/src/nicegui_notes/adapter/binding.py#nicegui-release -->

```python
def release_on_delete(*disposables: DisposableBase) -> DisposableBase:
    """Dispose ``disposables`` when NiceGUI deletes the current page's client.

    Returns them as one idempotent disposable, so a host can also release the
    page earlier, for example at shutdown.
    """
    page = CompositeDisposable(*disposables)
    ui.context.client.on_delete(page.dispose)
    return page
```

## 9.6.4. Host lifetime

NiceGUI owns the event loop, so the composition root captures it in
`app.on_startup` instead of creating one. NiceGUI starts an async startup
handler as a background task and serves pages without awaiting it, so a page
awaits the host's readiness before it reads the workspace. Shutdown handlers are
awaited. The host releases every page's bindings, then disposes the workspace
while the loop still runs, then shuts down the dispatcher's thread pool from
outside that pool, following
[Python asyncio dispatcher ownership](../primitives/services-messages-dispatching.md#669-python-asyncio-dispatcher-ownership):

<!-- checked-snippet: examples/python/nicegui/notes_showcase/src/nicegui_notes/host.py#nicegui-host -->

```python
def install(self, app: App) -> None:
    app.on_startup(self.start)
    app.on_shutdown(self.stop)

async def start(self) -> None:
    # RxDispatcher.asyncio(loop) gives foreground work affinity to the
    # loop NiceGUI is already running; VMx neither runs nor closes it.
    try:
        self.dispatcher = RxDispatcher.asyncio(asyncio.get_running_loop())
        workspace = (
            WorkspaceVM.builder()
            .repository(self._repository())
            .dispatcher(self.dispatcher)
            .build()
        )
        # construct_async is the only background hook the host admits, and
        # it completes before any page can bind.
        await workspace.construct_async()
        self.workspace = workspace
        self.accepting = True
    finally:
        self._started.set()  # a failed start releases waiting pages too

def adopt(self, page: DisposableBase) -> None:
    """Track a page's bindings so shutdown releases them before the workspace."""
    self._pages.add(page)
    ui.context.client.on_delete(lambda: self._pages.discard(page))

async def ready(self) -> bool:
    """Wait until startup has finished; True when the workspace is accepting pages."""
    await self._started.wait()
    return self.accepting

async def stop(self) -> None:
    # Shutdown order (Python asyncio dispatcher ownership): stop admitting
    # pages, release every page's subscriptions, dispose the workspace while
    # the loop still runs, then shut down the dispatcher's own thread pool
    # from outside that pool.
    self.accepting = False
    workspace, dispatcher = self.workspace, self.dispatcher
    self.workspace = None
    pages, self._pages = list(self._pages), set()
    try:
        for page in pages:
            page.dispose()
        if workspace is not None:
            workspace.dispose()
    finally:
        pool = dispatcher.background if dispatcher is not None else None
        if isinstance(pool, ThreadPoolScheduler):
            await asyncio.to_thread(pool.executor.shutdown, wait=True)
```

## 9.6.5. Page

The page holds no state. Every element reads from a view-model, every event
forwards to one. The editor pane binds the note form's fields and commands and
returns its bindings:

<!-- checked-snippet: examples/python/nicegui/notes_showcase/src/nicegui_notes/page.py#nicegui-editor -->

```python
def _editor_pane(workspace: WorkspaceVM) -> list[DisposableBase]:
    form = workspace.note_form
    with ui.column().classes("grow"):
        title = ui.input("Title").classes("w-full").mark("note-title")
        title_error = ui.label().classes("text-negative").mark("title-error")
        body = ui.textarea("Body").classes("w-full").mark("note-body")
        with ui.row():
            save = ui.button("Save").mark("save")
            revert = ui.button("Revert").mark("revert")
            dirty = ui.label().mark("dirty")
    return [
        bind_property_two_way(title, form, "title", text),
        bind_property(title_error, "text", form, "title_error", _error_text),
        bind_property_two_way(body, form, "body", text),
        bind_command(save, form.approve_command),
        bind_command(revert, form.deny_command),
        bind_derived_property(dirty, "text", form.is_dirty, _dirty_text),
    ]
```

The page builder awaits the host, builds the panes, and lets the host adopt the
page's bindings so shutdown can release them first:

<!-- checked-snippet: examples/python/nicegui/notes_showcase/src/nicegui_notes/page.py#nicegui-page -->

```python
async def build_page(host: NotesHost) -> None:
    """Build one client's page over the host's workspace."""
    workspace = host.workspace if await host.ready() else None
    if workspace is None:
        ui.label("The notes workspace is not running.")
        return
    with ui.row().classes("items-baseline"):
        ui.label("VMx Notes").classes("text-h5")
        status = ui.label().mark("status")
    with ui.row().classes("w-full no-wrap"):
        bindings = [_notebooks_pane(workspace), *_notes_pane(workspace), *_editor_pane(workspace)]
    bindings.append(bind_derived_property(status, "text", workspace.status_bar.note_count_text))
    host.adopt(release_on_delete(*bindings))
```

## 9.6.6. Fuller example

[`examples/python/nicegui/notes_showcase/`](../../../examples/python/nicegui/notes_showcase/)
is its own uv project, pinned to NiceGUI 3.x, so NiceGUI and its web stack stay
out of `vmx`. It reuses the Textual Notes-Showcase's models and view-models, and
duplicates none of them. Run it with `uv run python -m nicegui_notes` and open
<http://localhost:8080>.

Its tests cover each bridge, a reconnect followed by client deletion, a change
made on a worker thread, the host's startup and shutdown order, and a smoke test
that opens the page, edits the seed note "Standup notes", and saves it.
