# 6.3. Command Families

## When To Use It

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

## Shape And Ownership

The shipped command surface breaks down into a few layers:

- `RelayCommand` and parameterized `RelayCommand<T>`
- decorators: `CompositeCommand`, `DecoratorCommand`,
  `ConfirmationDecoratorCommand`
- fluent helpers: `Confirm`, `PrecedeWith`, `SucceedWith`, `WrapWith`
- `ModeledCrudCommands` for selection-driven create/update/delete bundles

Commands own their predicates, tasks, trigger subscriptions, and disposal
inertness. They do not own VM lifecycle.

## Lifecycle And Messaging

Commands become interesting when triggers are involved:

- predicates are pure gates for `CanExecute`
- tasks run only when predicates allow execution
- trigger emissions force re-evaluation and raise `CanExecuteChanged`
- disposed commands become inert and report `CanExecute == false`
- fire-and-forget confirmation flows surface asynchronous failures on an error
  observable instead of swallowing them

## Cross-Language Surface

Representative naming differences:

| Concept        | C#                       | Python                   | TypeScript               | Swift                    |
| -------------- | ------------------------ | ------------------------ | ------------------------ | ------------------------ |
| Builder entry  | `RelayCommand.Builder()` | `RelayCommand.builder()` | `RelayCommand.builder()` | `RelayCommand.builder()` |
| Trigger setter | `Triggers(...)`          | `triggers(...)`          | `triggers(...)`          | `triggers(...)`          |
| Confirm helper | extension `Confirm(...)` | `confirm(...)` helper    | `confirm(...)` helper    | `confirm(...)` helper    |

## Example

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

## Common Pitfalls

- Depending on mutable state in `CanExecute` without a trigger that raises
  `CanExecuteChanged`.
- Swallowing async confirmation or approve failures instead of observing their
  error channels.
- Re-implementing pre/post/confirm composition manually instead of using the
  decorator and fluent surfaces.

## Related Primitives

- [Composite Family](viewmodel-families/composite-family.md)
- [FormVM](viewmodel-families/specialized/form-vm.md)
- [Services, Messages & Dispatching](services-messages-dispatching.md)
