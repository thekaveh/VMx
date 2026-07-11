# 6.2.8.2. FormVM

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
- optional builder `resetOnApproved` / `ResetOnApproved` /
  `reset_on_approved`

## Lifecycle And Messaging

Construction captures the initial snapshot. After that:

- real model mutations recompute `IsDirty`
- validation re-runs on construct, set-model, and deny
- deny restores from the snapshot
- approve persists, advances the snapshot, and publishes `OnApproved`
- when configured, reset-after-approve derives a new pristine model from the
  captured persisted value before `OnApproved` fires
- fire-and-forget approve failures surface on `ApproveErrors`

Repeated disposal completes the owned channels and commands at most once while
preserving the form's inert post-dispose behavior. See the
[Disposal Contract](../../disposal-contract.md).

`SetModel` / `set_model` that begins after disposal is also a complete no-op.
It returns before null or equality work, leaves the live model and snapshot
unchanged, does not re-run validators, and cannot change errors, dirty/valid
state, approve command state, or notification channels. A set admitted before
disposal keeps the normal mutation contract. Upstream async work should still
be cancelled for resource control; this guard only rejects a late form result.

Strict mode gates approve on `IsValid && IsDirty`.

### Settled model publication

An accepted unequal `SetModel` / `set_model` call is one synchronous edit
transaction. VMx installs the candidate, recomputes validation, errors, dirty
state, and approve-command state, then publishes exactly one model
`PropertyChangedMessage` on the configured hub. Publication is last, so a
synchronous hub observer sees the complete settled form state. The property
name follows the flavor idiom: `"Model"` in C# and `"model"` in Python,
TypeScript, Swift, and Rust.

The equality check uses the same configured or idiomatic equality as dirty
tracking. An equal candidate is a complete no-op: VMx retains the current model
and does not validate, invalidate commands, or publish. A re-entrant observer
may assign another unequal value; each accepted call settles and publishes
once before returning.

`DenyCommand` keeps its explicit ordered pair: one `FormRevertedMessage`, then
one idiomatic model property message after the revert settles. A successful
reset-after-approve publishes through `OnApproved` only and does not emit a
model property message.

### Declarative submit-then-clear

Configure reset-after-approve when a successful submission should leave the
form pristine with a derived next model. VMx captures the model before awaiting
persistence, persists it, checks disposal, invokes the reset once, snapshots
the reset result twice for independent live and snapshot values, revalidates,
and commits the transition. `OnApproved` then emits the captured persisted
model while observers see the already-reset form.

The reset wins over a `SetModel` racing the persistence wait. It does not run
for invalid approval, persistence failure or cancellation, disposal during
persistence, or deny/revert. If the reset or snapshot preparation fails,
persistence has already succeeded but local state is not changed and
`OnApproved` does not fire. Awaitable approval throws that failure; the command
path emits it once on `ApproveErrors`. A retry can therefore repeat external
persistence and should be handled as such.

## Cross-Language Surface

| Concept           | C#                  | Python                | TypeScript             | Swift               | Rust                  |
| ----------------- | ------------------- | --------------------- | ---------------------- | ------------------- | --------------------- |
| Type              | `FormVM<TM>`        | `FormVM[TM]`          | `FormVM<TM>`           | `FormVM<Model>`     | `FormVm<M>`           |
| Builder           | `FormVMBuilder<TM>` | `FormVMBuilder[TM]`   | `FormVM.builder<TM>()` | builder surface     | `FormVm::builder()`   |
| Mutator           | `SetModel(...)`     | `set_model(...)`      | `setModel(...)`        | `setModel(...)`     | `set_model(...)`      |
| Awaitable/direct approve | `ApproveAsync()` | `approve_async()` | `approveAsync()`       | `approveAsync()`    | `approve()`           |
| Reset builder     | `ResetOnApproved`   | `reset_on_approved`   | `resetOnApproved`      | `resetOnApproved`   | `reset_on_approved`   |

Builder examples use the idiomatic name but the same captured-model contract:

=== "C#"

    ```csharp
    var form = FormVM<OrderDraft>.Builder()
        .Initial(initial)
        .Persister(SaveAsync)
        .ResetOnApproved(saved => OrderDraft.Empty(saved.CustomerId))
        .Build();
    ```

=== "Python"

    ```python
    form = (FormVM.builder()
        .initial(initial)
        .persister(save)
        .reset_on_approved(lambda saved: OrderDraft.empty(saved.customer_id))
        .build())
    ```

=== "TypeScript"

    ```typescript
    const form = FormVM.builder<OrderDraft>()
      .initial(initial)
      .persister(save)
      .resetOnApproved((saved) => OrderDraft.empty(saved.customerId))
      .build();
    ```

=== "Swift"

    ```swift
    let form = try FormVM<OrderDraft>.builder()
        .initial(initial)
        .persister(save)
        .resetOnApproved { saved in .empty(customerID: saved.customerID) }
        .build()
    ```

=== "Rust"

    ```rust
    let form = FormVm::builder()
        .initial(initial)
        .persister(save)
        .reset_on_approved(|saved| Ok(OrderDraft::empty(saved.customer_id)))
        .build()?;
    ```

## Example

The Notes Workspace editor is the best concrete reference:

- C#: [NoteFormVM.cs](../../../../../examples/csharp/avalonia/NotesShowcase/ViewModels/NoteFormVM.cs)
- Python: [note_form_vm.py](../../../../../examples/python/textual/notes_showcase/src/notes_showcase/viewmodels/note_form_vm.py)
- TypeScript: [noteFormVM.ts](../../../../../examples/typescript/react/notes-showcase/src/viewmodels/noteFormVM.ts)
- Swift: [NoteFormVM.swift](../../../../../examples/swift/notes-showcase/Sources/NotesShowcaseCore/ViewModels/NoteFormVM.swift)

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

## TypeScript Cloneability And Tableau Migration

TypeScript uses `structuredClone` for the default snapshot. Functions,
`WeakMap`/`WeakSet`, host handles, and objects containing those values are not
structured-cloneable. If the default fails during construction, approve
snapshot advance, or deny/revert, `FormVM` reports that phase and the first
failing enumerable top-level field it can safely identify. The native error is
preserved as `cause`; the diagnostic never renders field values.

Field localization inspects data-property descriptors, performs no writes, and
does not invoke getters a second time. User-defined accessors or proxy traps can
have side effects during the original `structuredClone` call or descriptor
inspection, so `FormVM` deliberately omits the field name when localization
cannot be guaranteed.

Tableau's genesis form carries an opaque `imagePayload` beside ordinary form
data. Keep the opaque value by reference, explicitly define which plain fields
participate in dirty tracking, and configure both hooks together:

```typescript
const snapshotGenesis = (model: GenesisModel): GenesisModel => ({
  ...structuredClone({ prompt: model.prompt, seed: model.seed }),
  imagePayload: model.imagePayload,
});

const equalsGenesis = (a: GenesisModel, b: GenesisModel): boolean =>
  a.prompt === b.prompt && a.seed === b.seed;

const form = FormVM.builder<GenesisModel>()
  .initial(initial)
  .persister(persistGenesis)
  .snapshotter(snapshotGenesis)
  .equals(equalsGenesis)
  .resetOnApproved((approved) => ({
    ...approved,
    imagePayload: undefined,
  }))
  .build();
```

Here `imagePayload` is intentionally excluded from dirty tracking, restored by
reference on deny, and cleared only after its captured value has been
successfully persisted. This replaces a persister closure that captured the
not-yet-created form merely to call `setModel` at the end. If reference identity should count as dirty,
include `a.imagePayload === b.imagePayload` in `equalsGenesis`. VMx does not
provide `snapshotExclude`: exclusion without an explicit equality policy would
make dirty and revert semantics ambiguous.

## Common Pitfalls

- Treating `FormVM` as a drop-in `ComponentVM` subclass. It is a distinct
  workflow primitive.
- Relying on shallow copy semantics for nested mutable models. Inject a custom
  snapshotter and matching equality predicate where the default is not
  appropriate.
- Ignoring `ApproveErrors` on fire-and-forget command paths.
- Retrying blindly after reset failure; the external persist already succeeded.
- Re-implementing save/cancel/dirty plumbing in every editor instead of
  composing the primitive once.
- Keeping a form-specific “zombie assignment” flag solely to stop late
  `setModel` calls. VMx now rejects those calls after disposal; retain only
  cancellation that still owns application resources.

## Related Primitives

- [Component Family](../component-family.md)
- [DiscriminatorVM](discriminator-vm.md)
- [State & Reactive Helpers](../../state-reactive-helpers.md)
