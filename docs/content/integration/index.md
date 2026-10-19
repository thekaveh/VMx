# 9.1. Integration Recipes

These framework-specific recipes show how VMx state and commands cross a host
framework's binding, lifecycle, and dispatcher boundaries.

## 9.1.1. What The Recipes Cover

Each recipe summarizes the same adapter problem:

- bridge VMx property-change events into the host framework's reactivity model
- route host actions back into `RelayCommand` or related command surfaces
- keep collection updates and dispatcher marshalling inside the adapter boundary

## 9.1.2. Current Recipes

### 9.1.2.1. C\#

- [Avalonia](avalonia.md)
- [WPF](wpf.md)
- [MAUI](maui.md)

### 9.1.2.2. Python

- [Textual](textual.md)
- [NiceGUI](nicegui.md)
- [tkinter](tkinter.md)

### 9.1.2.3. TypeScript

- [React](react.md)
- [Vue 3](vue.md)
- [Svelte](svelte.md)
- [SolidJS](solid.md)

### 9.1.2.4. Swift

- [SwiftUI](swiftui.md)

### 9.1.2.5. Rust

Rust has no recipe page. The Ratatui terminal Notes Workspace in
[Worked Examples](#917-worked-examples) is the Rust host reference.

## 9.1.3. Imperative Engine And Uniform Bridge

Imperative engines do not need a render loop to poll VM state. Subscribe to the
selected value once, update the engine only when it changes, and let the host
adapter own the returned handle:

<!-- checked-snippet: langs/typescript/tests/unit/imperativeBridgeRecipe.test.ts#imperative-bridge -->

```typescript
const exposureSubscription = subscribeValue(
  cameraVm,
  vm => vm.model.exposure,
  exposure => { material.uniforms.exposure.value = exposure; },
  { fireImmediately: true },
);
```

Dispose the bridge with the adapter that owns `material`:

<!-- checked-snippet: langs/typescript/tests/unit/imperativeBridgeRecipe.test.ts#imperative-bridge-dispose -->

```typescript
exposureSubscription.unsubscribe();
```

The callbacks behave as follows:

- **Initial delivery.** VMx invokes the immediate callback synchronously,
  before it attaches the hub subscription. The callback receives the selected
  value as both current and previous. During adapter setup, this sets the
  uniform before the adapter starts its first frame.
- **Later deliveries.** VMx reevaluates the selector after any property message
  from this fixed `cameraVm`. The callback receives the changed current value
  and the prior selected value.
- **Equality.** `Object.is` suppresses unchanged selections by default. The
  `equality` option supplies a domain-specific comparison.

The bridge is change-driven rather than frame-polled, so the renderer does no
selector work on quiet frames. Hub batches still deliver every property
message, but repeated deliveries that all see the same final exposure snapshot
collapse through equality. Initial setup failures propagate before attachment;
delivery failures use the hub's isolated subscriber-error path.

This recipe observes one fixed VM. For collection-member
discovery and dynamic fan-in, use `AggregateChangeStream` (ADR-0098).

## 9.1.4. Republished Models Keep Their Reference

`republishModel()` announces a model that was mutated in place. The announced
value is the same object that a binding already holds. A host primitive that
skips same-reference updates does not re-render, so each recipe forces the
update; the recipe page states its mechanism. Replacement objects and scalar
values update the same way.

## 9.1.5. Connection State

`AsyncResourceVM` models one value the UI requests and waits for. A long-lived
connection that drops and re-establishes itself, such as a frame stream, a
socket, or a server subscription, has a different shape: nothing requests it,
it can retry many times, and it ends. Model its state as a `ComponentVMOf` over
an immutable value with three states, and pass every report through one
function that enforces the rules:

- Connected and Reconnecting can follow each other any number of times.
  Reconnecting carries the reason the transport gave.
- Disconnected is terminal. Once the feed reaches it, later reports are ignored.
- A report equal to the current state publishes nothing, so a retry loop does
  not make the published state flicker at backoff frequency. A changed reason is
  a new state and publishes once.

<!-- checked-snippet: langs/python/tests/unit/state/test_connection_state_recipe.py#connection-state -->

```python
class Feed(Enum):
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"


@dataclass(frozen=True)
class FeedState:
    status: Feed
    reason: str | None = None


def advance(current: FeedState, reported: FeedState) -> FeedState:
    """Disconnected is terminal: no later report moves the feed out of it."""
    return current if current.status is Feed.DISCONNECTED else reported
```

The transport adapter reports each event through `advance`, and the view binds
to the VM's `model`:

<!-- checked-snippet: langs/python/tests/unit/state/test_connection_state_recipe.py#connection-state-retries -->

```python
def report(state: FeedState) -> None:
    feed.model = advance(feed.model, state)

for _attempt in range(5):
    report(FeedState(Feed.RECONNECTING, "server restarting"))
# Equal frozen dataclasses compare equal, so only the first retry publishes.
```

The suppression comes from `ComponentVMOf`, which publishes nothing when the
new model equals the current one. Python compares with `==`, C# with
`EqualityComparer<M>.Default`, Swift with `==` for an `Equatable` model, and
Rust with `PartialEq`, so a frozen dataclass, `record`, `Equatable` struct, or
`PartialEq` enum works as shown. TypeScript compares with `===`, so a fresh
object for every retry would publish every time. Its `advance` keeps the
current instance when the status and reason are unchanged:

<!-- checked-snippet: langs/typescript/tests/unit/connectionStateRecipe.test.ts#connection-state -->

```typescript
type FeedState =
  | { readonly status: "connected" }
  | { readonly status: "reconnecting"; readonly reason: string }
  | { readonly status: "disconnected"; readonly reason?: string };

const reasonOf = (state: FeedState) => ("reason" in state ? state.reason : undefined);

function advance(current: FeedState, reported: FeedState): FeedState {
  // Disconnected is terminal: no later report moves the feed out of it.
  if (current.status === "disconnected") return current;
  // ComponentVMOf compares models with ===, so a fresh but equal object would
  // publish again. Keep the current instance when nothing changed.
  const unchanged = reported.status === current.status && reasonOf(reported) === reasonOf(current);
  return unchanged ? current : reported;
}
```

The recipe runs as
`langs/python/tests/unit/state/test_connection_state_recipe.py` and
`langs/typescript/tests/unit/connectionStateRecipe.test.ts`. Both drive five
retries with one reason, a changed reason, and a reconnect after Disconnected,
and count the hub's `PropertyChangedMessage`s for `model`.

Use `AsyncResourceVM` when the UI asks for a value and may reload or cancel it.
Use this recipe when a transport pushes a connection's state over time. The
stream that produces the reports, retry backoff, and offline presentation stay
outside it.

## 9.1.6. JavaScript Signals Posture

VMx keeps RxJS as its TypeScript reactive primitive and ships no Signals
polyfill, helper, or subpath while the TC39 Signals proposal is below Stage 2.
[ADR-0101](../../../spec/ADRs/0101-hold-rx-and-gate-tc39-signals-interop.md)
lists the gates for reconsidering Signals interop; until then, use hub
messages, VM-local streams, `DerivedProperty`, and `subscribeValue`.

## 9.1.7. Worked Examples

- Avalonia Notes Workspace:
  [examples/csharp/avalonia/NotesShowcase/README.md](../../../examples/csharp/avalonia/NotesShowcase/README.md)
- Textual Notes Workspace:
  [examples/python/textual/notes_showcase/README.md](../../../examples/python/textual/notes_showcase/README.md)
- React Notes Workspace:
  [examples/typescript/react/notes-showcase/README.md](../../../examples/typescript/react/notes-showcase/README.md)
- Swift Notes Workspace:
  [examples/swift/notes-showcase/README.md](../../../examples/swift/notes-showcase/README.md)
- NiceGUI Notes Workspace:
  [examples/python/nicegui/notes_showcase/README.md](../../../examples/python/nicegui/notes_showcase/README.md)
- Rust Notes Workspace (Ratatui TUI, no recipe page):
  [examples/rust/README.md](../../../examples/rust/README.md)
- WPF TodoApp:
  [examples/csharp/wpf/TodoApp/](../../../examples/csharp/wpf/TodoApp/)
- Tkinter todo app:
  [examples/python/tk/todo_app/](../../../examples/python/tk/todo_app/)

## 9.1.8. How The Recipes Are Checked

A recipe fence preceded by a `<!-- checked-snippet: path -->` or
`<!-- checked-snippet: path#region -->` comment is a copy of code that CI
compiles and runs. `make docs-check` fails when the fence differs from that
file, or from the lines between `docs-snippet:start <region>` and
`docs-snippet:end <region>` in it. Names a fence does not define, such as `vm`
or `app`, stand for the application's own objects; the checked source defines
them before the region.

| Recipe                        | Checked source                                                                                             | CI job                                                                   | What runs                                                                                                                           |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| Vue, Solid, Svelte            | `examples/typescript/integration-recipes/`                                                                 | typescript `examples (notes-showcase)`, Linux                            | Executed on jsdom: initial value, mutation, command, reconnect, cleanup                                                             |
| React                         | `examples/typescript/react/notes-showcase/tests/recipes/reactRecipe.test.tsx`                              | typescript `examples (notes-showcase)`, Linux                            | Executed on jsdom; the install command is not checked                                                                               |
| Imperative bridge (this page) | `langs/typescript/tests/unit/imperativeBridgeRecipe.test.ts`                                               | typescript `build & test`                                                | Executed                                                                                                                            |
| WPF                           | `langs/csharp/tests/VMx.Tests/Integration/BindableVm.cs`, `examples/csharp/wpf/RecipeHostCheck/Program.cs` | csharp `build & test`; `example + recipe host (WPF / Windows, executed)` | Executed on test schedulers and on a real WPF Dispatcher                                                                            |
| MAUI                          | `BindableVm.cs`, `XamlRecipeTests.cs`                                                                      | csharp `build & test`                                                    | Adapter executed; CI has no MAUI host, so the page statement runs against a stand-in page                                           |
| Textual                       | `examples/python/textual/notes_showcase/tests/views/textual_recipe.py`                                     | python `examples (notes-showcase)`                                       | Executed in a headless Textual app                                                                                                  |
| SwiftUI                       | `langs/swift/Tests/VMxTests/SwiftUIRecipeTests.swift`                                                      | swift `build & test`, macOS                                              | Adapter executed; the view is compile-only and never rendered                                                                       |
| Avalonia                      | `BindableVm.cs`, `examples/csharp/avalonia/NotesShowcase.Tests/Views/AvaloniaRecipeTests.cs`               | csharp `examples (notes-showcase)`, Linux                                | Executed with real Avalonia bindings on Avalonia's headless UI thread                                                               |
| Tkinter                       | `examples/python/tk/note_recipe/`                                                                          | python `examples (console + tk)`, Linux                                  | Executed on a real Tk root under Xvfb; `run()` is type-checked, not executed                                                        |
| NiceGUI                       | `examples/python/nicegui/notes_showcase/src/nicegui_notes/`                                                | python `examples (nicegui)`, Linux                                       | Executed in NiceGUI's user simulation: each bridge, reconnect and deletion, a worker-thread change, host shutdown, and a smoke test |

## 9.1.9. Host Coverage

Three kinds of checks cover the desktop hosts, and they prove different things.
Headless tests run the view-models and adapters without a UI toolkit.
Compilation proves the host code builds for a platform. Only host execution
runs the toolkit's own event loop, so only it can catch a binding, delivery, or
teardown regression in the host.

| Host               | Headless tests                                                                  | Platform compilation                                                                | Host execution                                                                                                                          |
| ------------------ | ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Tkinter            | none beyond the VMx Python suite                                                | `compileall tk/todo_app` and `mypy --strict`, python `examples (console + tk)`      | `todo_app.host_check` and `note_recipe` on a real Tk root under Xvfb, same job, Linux                                                   |
| WPF                | `BindableVm` on test schedulers, csharp `build & test`                          | `dotnet build WpfTodoApp.csproj`, `example + recipe host (WPF / Windows, executed)` | `TodoAppHostCheck` and `RecipeHostCheck` on a real STA Dispatcher, same job, `windows-latest`                                           |
| SwiftUI (macOS)    | NotesShowcase VM suites; `SwiftUIRecipeTests` in the VMx Swift suite            | `swift build`, including strict concurrency, swift `examples (notes-showcase)`      | `HostLifecycleTests` hosts a view in an `NSWindow` on macOS 15: appear, worker change delivered on the main thread, disappear; same job |
| Avalonia           | NotesShowcase VM suites; `BindableVm` on test schedulers, csharp `build & test` | `dotnet build NotesShowcase.csproj`, csharp `examples (notes-showcase)`, Linux      | `AvaloniaRecipeTests` on Avalonia's headless platform: real bindings and UI thread, no native window; same job                          |
| iOS, tvOS, watchOS | the same Swift suites, run on macOS                                             | `xcodebuild build` for generic destinations, swift `build (iOS 16)` and siblings    | none: no simulator runs in CI                                                                                                           |

The Tk, WPF, and macOS host checks wait on the host's own idle, dispatcher, or
run-loop signals with a bounded timeout, never on a fixed sleep. The Tk and WPF
checks print every step they checked; the macOS test reports through XCTest.
