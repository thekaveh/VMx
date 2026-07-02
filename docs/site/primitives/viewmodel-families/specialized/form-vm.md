# FormVM

## When To Use It

Use `FormVM<TM>` when the user edits a working copy, then either approves the
changes or denies them and reverts to the last snapshot. This is the right
primitive for editors, settings forms, CRUD dialogs, and other explicit
edit-save-cancel workflows.

<img src="../../../../assets/diagrams/forms-dialogs-notifications.svg" alt="Forms Dialogs And Notifications Flow" class="vmx-diagram" />

<p>
  <a href="../../../../assets/diagrams/forms-dialogs-notifications.html">HTML</a>
  &middot;
  <a href="../../../../assets/diagrams/forms-dialogs-notifications.svg">SVG</a>
  &middot;
  <a href="../../../../assets/diagrams/forms-dialogs-notifications.png">PNG</a>
</p>

## Shape And Ownership

`FormVM` owns a live `Model`, a `Snapshot`, dirty tracking, validation state,
and approve/deny commands. It is not a leaf container and it is not a subclass
of `ComponentVM`; consumers typically compose it inside another VM that exposes
the host-specific editor surface.

Important members:

- `Model` plus `SetModel(...)`
- `Snapshot`
- `IsDirty`
- `Errors`, `IsValid`, `FieldError(...)`
- `ApproveCommand`, `ApproveAsync()`, `ApproveErrors`
- `DenyCommand`

## Lifecycle And Messaging

Construction captures the initial snapshot. After that:

- real model mutations recompute `IsDirty`
- validation re-runs on construct, set-model, and deny
- deny restores from the snapshot
- approve persists, advances the snapshot, and publishes `OnApproved`
- fire-and-forget approve failures surface on `ApproveErrors`

Strict mode gates approve on `IsValid && IsDirty`.

## Cross-Language Surface

| Concept           | C#                  | Python              | TypeScript             | Swift            |
| ----------------- | ------------------- | ------------------- | ---------------------- | ---------------- |
| Type              | `FormVM<TM>`        | `FormVM[TM]`        | `FormVM<TM>`           | `FormVM<Model>`  |
| Builder           | `FormVMBuilder<TM>` | `FormVMBuilder[TM]` | `FormVM.builder<TM>()` | builder surface  |
| Mutator           | `SetModel(...)`     | `set_model(...)`    | `setModel(...)`        | `setModel(...)`  |
| Awaitable approve | `ApproveAsync()`    | `approve_async()`   | `approveAsync()`       | `approveAsync()` |

## Example

The Notes Workspace editor is the best concrete reference:

- C#: [NoteFormVM.cs](https://github.com/thekaveh/VMx/blob/main/examples/csharp/avalonia/NotesShowcase/ViewModels/NoteFormVM.cs)
- Python: [note_form_vm.py](https://github.com/thekaveh/VMx/blob/main/examples/python/textual/notes_showcase/src/notes_showcase/viewmodels/note_form_vm.py)
- TypeScript: [noteFormVM.ts](https://github.com/thekaveh/VMx/blob/main/examples/typescript/react/notes-showcase/src/viewmodels/noteFormVM.ts)
- Swift: [NoteFormVM.swift](https://github.com/thekaveh/VMx/blob/main/examples/swift/notes-showcase/Sources/NotesShowcaseCore/ViewModels/NoteFormVM.swift)

All four compose a strict inner `FormVM` rather than subclassing it, then layer
editor-specific commands and notifications around that core workflow.

=== "C#"

    ```csharp
    _form = new FormVM<NoteModel>(
        initial: note,
        persister: PersistAsync,
        hub: Hub,
        strict: true,
        validators: new Dictionary<string, Func<NoteModel, string?>>
        {
            [nameof(Title)] = note => string.IsNullOrWhiteSpace(note.Title) ? TitleRequired : null
        });
    ```

=== "Python"

    ```python
    form = FormVM(
        initial=note,
        persister=self._persist,
        hub=self._hub,
        strict=True,
        validators={"title": lambda m: _TITLE_REQUIRED if not m.title.strip() else None},
    )
    ```

=== "TypeScript"

    ```ts
    this.#form = new FormVM<NoteModel>({
      initial: note,
      persister: (m) => this.#persistAsync(m),
      hub: this._hub,
      strict: true,
      validators: {
        title: (m) => m.title.trim().length === 0 ? TITLE_REQUIRED : null,
      },
    });
    ```

=== "Swift"

    ```swift
    let form = FormVM<NoteModel>(
        initial: note,
        persister: { [weak self] n in
            guard let self else { return }
            try await self._repo.saveNote(n)
        },
        hub: hub,
        strict: true,
        validators: [
            "title": { model in
                model.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    ? Self.titleRequired
                    : nil
            }
        ]
    )
    ```

## Common Pitfalls

- Treating `FormVM` as a drop-in `ComponentVM` subclass. It is a distinct
  workflow primitive.
- Relying on shallow copy semantics for nested mutable models. Inject a custom
  snapshotter where the default is not appropriate.
- Ignoring `ApproveErrors` on fire-and-forget command paths.
- Re-implementing save/cancel/dirty plumbing in every editor instead of
  composing the primitive once.

## Related Primitives

- [Component Family](../component-family.md)
- [DiscriminatorVM](discriminator-vm.md)
- [State & Reactive Helpers](../../state-reactive-helpers.md)
