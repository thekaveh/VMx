# DiscriminatorVM

## When To Use It

Use `DiscriminatorVM<TKey>` when one VM needs a single source of truth for an
active pane, editor mode, route, focus target, or modal precedence stack.

It is intentionally small: state coordination, not child ownership.

## Shape And Ownership

`DiscriminatorVM` owns one `ActiveKey` plus an internal modal stack used by
`ModalOpen(...)` and `ModalClose()`. It does not own the panes, routes, or
modal VMs themselves. Those remain external.

Core members:

- `ActiveKey`
- `ActiveChanged`
- `IsActive(key)`
- `SetActiveKey(key)`
- `ModalOpen(modalKey)`
- `ModalClose()`

## Lifecycle And Messaging

The behavior is straightforward and important:

- setting the same key is a no-op
- setting a different key updates state and emits one change
- modal opens push the prior active key
- modal closes restore keys in LIFO order
- dispose completes the change stream and makes later mutations inert

## Cross-Language Surface

| Concept       | C#               | Python            | TypeScript       | Swift            |
| ------------- | ---------------- | ----------------- | ---------------- | ---------------- |
| Active key    | `ActiveKey`      | `active_key`      | `activeKey`      | `activeKey`      |
| Change stream | `ActiveChanged`  | `active_changed`  | `activeChanged`  | `activeChanged`  |
| Open modal    | `ModalOpen(...)` | `modal_open(...)` | `modalOpen(...)` | `modalOpen(...)` |

## Example

The Notes Workspace editor mode is the concrete showcase feature:

- C#: [NoteFormVM.cs](https://github.com/thekaveh/VMx/blob/main/examples/csharp/avalonia/NotesShowcase/ViewModels/NoteFormVM.cs)
- Python: [note_form_vm.py](https://github.com/thekaveh/VMx/blob/main/examples/python/textual/notes_showcase/src/notes_showcase/viewmodels/note_form_vm.py)
- TypeScript: [noteFormVM.ts](https://github.com/thekaveh/VMx/blob/main/examples/typescript/react/notes-showcase/src/viewmodels/noteFormVM.ts)
- Swift: [NoteFormVM.swift](https://github.com/thekaveh/VMx/blob/main/examples/swift/notes-showcase/Sources/NotesShowcaseCore/ViewModels/NoteFormVM.swift)

Each editor keeps `"edit"` and `"preview"` in a `DiscriminatorVM` instead of
spreading active-mode booleans across unrelated properties.

=== "C#"

````
```csharp
private readonly DiscriminatorVM<string> _editorMode = new("edit");
public string EditorMode => _editorMode.ActiveKey;
public bool IsPreviewMode => _editorMode.IsActive("preview");
```
````

=== "Python"

````
```python
self._editor_mode: DiscriminatorVM[str] = DiscriminatorVM("edit")

@property
def is_preview_mode(self) -> bool:
    return self._editor_mode.is_active("preview")
```
````

=== "TypeScript"

````
```ts
readonly #editorMode = new DiscriminatorVM<EditorMode>("edit");

get isPreviewMode(): boolean {
  return this.#editorMode.isActive("preview");
}
```
````

=== "Swift"

````
```swift
private let _editorMode = DiscriminatorVM<String>(initial: "edit")

public var isPreviewMode: Bool {
    _editorMode.isActive("preview")
}
```
````

## Common Pitfalls

- Using a discriminator as a container. It coordinates keys; it does not own
  child VMs.
- Duplicating the same active-mode state in multiple booleans and then having
  to reconcile them manually.
- Forgetting that modal precedence is stack-based; nested modal restore order is
  LIFO by contract.

## Related Primitives

- [FormVM](form-vm.md)
- [ModalVM](modal-vm.md)
- [Services, Messages & Dispatching](../../services-messages-dispatching.md)
