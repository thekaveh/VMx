# 6.3. Command Families

## 6.3.1. When To Use It

Use the command family when behavior should be executable, bindable, and
reactively re-evaluated without baking that behavior into the VM hierarchy
itself.

Start with `RelayCommand`; add composition or confirmation only when the
workflow needs it.

<img src="../../assets/diagrams/commands-capabilities.svg" alt="Commands And Capabilities Map" class="vmx-diagram" />

<p>
  <a href="../../assets/diagrams/commands-capabilities.html">HTML</a>
  &middot;
  <a href="../../assets/diagrams/commands-capabilities.svg">SVG</a>
  &middot;
  <a href="../../assets/diagrams/commands-capabilities.png">PNG</a>
</p>

## 6.3.2. Shape And Ownership

The shipped command surface breaks down into a few layers:

- `RelayCommand`, parameterized `RelayCommand<T>`, and `AsyncRelayCommand`
- decorators: `CompositeCommand`, `DecoratorCommand`,
  `ConfirmationDecoratorCommand`
- fluent helpers: `Confirm`, `PrecedeWith`, `SucceedWith`, `WrapWith`
- `ModeledCrudCommands` for selection-driven create/update/delete bundles

Commands own their predicates, tasks, trigger subscriptions, and disposal
inertness. They do not own VM lifecycle.

## 6.3.3. Lifecycle And Messaging

Commands become interesting when triggers are involved:

- predicates are pure gates for `CanExecute`
- tasks run only when predicates allow execution
- trigger emissions force re-evaluation and raise `CanExecuteChanged`
- imperative raise methods notify bindings when a predicate depends on
  non-observable host state
- disposed commands become inert and report `CanExecute == false`
- fire-and-forget confirmation flows surface asynchronous failures on an error
  observable instead of swallowing them

Repeated command disposal, including during an in-flight async operation,
follows the [Disposal Contract](disposal-contract.md): cancellation and terminal
completion occur at most once.

## 6.3.4. Cross-Language Surface

Representative naming differences:

| Concept          | C#                         | Python                        | TypeScript                 | Swift                      | Rust                          |
| ---------------- | -------------------------- | ----------------------------- | -------------------------- | -------------------------- | ----------------------------- |
| Builder entry    | `RelayCommand.Builder()`   | `RelayCommand.builder()`      | `RelayCommand.builder()`   | `RelayCommand.builder()`   | `RelayCommand::builder()`     |
| Trigger setter   | `Triggers(...)`            | `triggers(...)`               | `triggers(...)`            | `triggers(...)`            | `trigger(...)`                |
| Imperative raise | `RaiseCanExecuteChanged()` | `raise_can_execute_changed()` | `raiseCanExecuteChanged()` | `raiseCanExecuteChanged()` | `raise_can_execute_changed()` |
| Confirm helper   | extension `Confirm(...)`   | `confirm(...)` helper         | `confirm(...)` helper      | `confirm(...)` helper      | `confirm(...)`                |

## 6.3.5. Triggers Or Imperative Raise?

Use a trigger when the predicate dependency already has an observable stream.
The command owns that subscription and every trigger emission publishes one
`CanExecuteChanged` notification.

Use the imperative method when host state changes through a non-observable API,
or when a binding adapter explicitly knows that a predicate may have changed.
The method publishes one notification only: it does not call the predicate,
execute the task, or start an async command.

=== "C#"

    ```csharp
    isDirty = true;
    saveCommand.RaiseCanExecuteChanged();
    ```

=== "Python"

    ```python
    is_dirty = True
    save_command.raise_can_execute_changed()
    ```

=== "TypeScript"

    ```ts
    isDirty = true;
    saveCommand.raiseCanExecuteChanged();
    ```

=== "Swift"

    ```swift
    isDirty = true
    saveCommand.raiseCanExecuteChanged()
    ```

=== "Rust"

    ```rust
    is_dirty.store(true, Ordering::SeqCst);
    save_command.raise_can_execute_changed();
    ```

Repeated calls and trigger emissions remain additive. The same operation is
available on parameterized and async relay commands, including while an async
execution is in flight. Calls after disposal are safe no-ops.

The operation belongs to concrete relay commands. `CompositeCommand` and the
decorators forward inner `CanExecuteChanged` notifications but do not expose a
synthetic raise method. Retain the owning relay reference when decorating a
command that needs imperative invalidation.

## 6.3.6. Example

Canonical relay-command shape:

=== "TypeScript"

    ```ts
    const save = RelayCommand.builder()
      .predicate(() => form.isDirty && form.isValid)
      .task(() => {
        void form.approveAsync();
      })
      .triggers(currentChanged)
      .build();
    ```

The same structure appears across all full-parity source flavors with only
casing and trait-import changes.
The Notes Workspace editor and delete flows are concrete examples.

## 6.3.7. Common Pitfalls

- Depending on mutable state in `CanExecute` without a trigger that raises
  `CanExecuteChanged` or an explicit imperative raise at the mutation site.
- Polling every command on every UI render instead of subscribing to
  `CanExecuteChanged` and invalidating only when the predicate may have changed.
- Swallowing async confirmation or approve failures instead of observing their
  error channels.
- Re-implementing pre/post/confirm composition manually instead of using the
  decorator and fluent surfaces.

## 6.3.8. Related Primitives

- [Composite Family](viewmodel-families/composite-family.md)
- [FormVM](viewmodel-families/specialized/form-vm.md)
- [Services, Messages & Dispatching](services-messages-dispatching.md)
