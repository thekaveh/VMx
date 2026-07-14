# 6.2.8.6. ModalVM

## 6.2.8.6.1. When To Use It

Use `ModalVM` when a modal interaction should be represented as a VM-backed
result that host services can present and await. It fits domain-specific modal
flows that do not belong in the fixed `PickFile*`, `Confirm`, or `Notify`
methods on `IDialogService`.

## 6.2.8.6.2. Shape And Ownership

The core contract is small:

- cancellation result
- eventual result
- dismissed flag
- awaitable completion
- idempotent dismiss and dispose

Swift exposes the contract as `ModalVM` plus the concrete `BasicModalVM<Result>`
helper; the other flavors ship `ModalVM<T>` directly.

## 6.2.8.6.3. Lifecycle And Messaging

Modal completion is single-winner and host-driven:

- `Dismiss(result)` completes the modal exactly once
- `Dispose()` completes it with the cancellation result
- null dialog presentation returns the cancellation result immediately
- awaiters never hang if the modal is disposed instead of explicitly dismissed

Repeated disposal never replaces a prior result or resumes awaiters twice. See
the [Disposal Contract](../../disposal-contract.md).

## 6.2.8.6.4. Cross-Language Surface

| Concept          | C#             | Python          | TypeScript     | Swift                  |
| ---------------- | -------------- | --------------- | -------------- | ---------------------- |
| Concrete helper  | `ModalVM<T>`   | `ModalVM[T]`    | `ModalVM<T>`   | `BasicModalVM<Result>` |
| Awaitable result | `Completion`   | `wait_result()` | `completion`   | `waitResult()`         |
| Dismiss method   | `Dismiss(...)` | `dismiss(...)`  | `dismiss(...)` | `dismiss(...)`         |

## 6.2.8.6.5. Example

The Notes Workspace adapters mostly use the closed `Confirm` and `Notify`
dialog-service methods, but the modal primitive is the extension point behind
`IDialogService.Present(...)`.

Relevant shipped surfaces:

- C#: `VMx.Dialogs.ModalVM<T>` and `NullDialogService.Present(...)`
- Python: `vmx.dialogs.ModalVM`
- TypeScript: `src/dialogs/modalVM.ts`
- Swift: `ModalVM` protocol plus `BasicModalVM<Result>`

Use this primitive when you need a VM-backed modal result instead of a fixed
host dialog verb.

=== "C#"

    ```csharp
    var modal = new ModalVM<string>("cancel");
    modal.Dismiss("save");
    var result = await modal.Completion;
    ```

=== "Python"

    ```python
    modal = ModalVM[str]("cancel")
    modal.dismiss("save")
    result = await modal.wait_result()
    ```

=== "TypeScript"

    ```ts
    const modal = new ModalVM("cancel");
    modal.dismiss("save");
    const result = await modal.completion;
    ```

=== "Swift"

    ```swift
    let modal = BasicModalVM<String>(cancellationResult: "cancel")
    modal.dismiss("save")
    let result = await modal.waitResult()
    ```

## 6.2.8.6.6. Common Pitfalls

- Reaching for a modal VM when `Confirm`, `PickFileToOpen`, `PickFileToSave`, or
  `Notify` already matches the interaction.
- Forgetting that disposal is a completion path, not just cleanup.
- Assuming Swift's concrete helper is named exactly like the protocol. The
  helper is `BasicModalVM`.

## 6.2.8.6.7. Related Primitives

- [DiscriminatorVM](discriminator-vm.md)
- [Services, Messages & Dispatching](../../services-messages-dispatching.md)
- [ConfirmationVM](confirmation-vm.md)
