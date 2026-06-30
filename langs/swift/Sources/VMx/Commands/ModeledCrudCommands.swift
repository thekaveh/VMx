//
// ModeledCrudCommands — Create / UpdateCurrent / DeleteCurrent helper.
//
// See spec/06-composite-vm.md §7 and ADR-0016.
//
// Note: Swift drops the phantom `M` type parameter present in C# / Python / TS
// (see ADR-0006 §3.2 — phantom types are not idiomatic in Swift). The helper
// is parameterised only on VM (the view-model type).
//
import Foundation
import Combine

/// Packages the three canonical CRUD commands — `createNewCommand`,
/// `updateCurrentCommand`, `deleteCurrentCommand` — over a "currently
/// selected" view-model of type `VM`.
///
/// - `createNewCommand`: always executable; runs `createNew`.
/// - `updateCurrentCommand`: enabled only when `current()` returns non-nil;
///   runs `updateCurrent(vm)`. Optionally gated by a `confirmUpdate` delegate.
/// - `deleteCurrentCommand`: enabled only when `current()` returns non-nil;
///   runs `deleteCurrent(vm)`. Optionally gated by a `confirmDelete` delegate.
///
/// Pass `currentChanged` to wire a trigger so `canExecuteChanged` fires
/// whenever the selection changes and consumers can refresh button state.
public final class ModeledCrudCommands<VM: AnyObject> {
    public let createNewCommand: Command
    public let updateCurrentCommand: Command
    public let deleteCurrentCommand: Command

    // Inner RelayCommands hold trigger subscriptions; tracked so dispose() can
    // tear them down (parity with C# ModeledCrudCommands.Dispose).
    private let innerRelays: [RelayCommand]
    private var disposed = false

    public init(
        current: @escaping () -> VM?,
        createNew: @escaping () -> Void,
        updateCurrent: @escaping (VM) -> Void,
        deleteCurrent: @escaping (VM) -> Void,
        confirmUpdate: (() async throws -> Bool)? = nil,
        confirmDelete: (() async throws -> Bool)? = nil,
        currentChanged: AnyPublisher<Void, Never>? = nil
    ) {
        // create: no predicate — always executable.
        let create = RelayCommand.builder()
            .task(createNew)
            .build()

        // update: gated on current() != nil; optional currentChanged trigger.
        var updateBuilder = RelayCommand.builder()
            .task({ if let c = current() { updateCurrent(c) } })
            .predicate({ current() != nil })
        if let changed = currentChanged {
            updateBuilder = updateBuilder.triggers(changed)
        }
        let update = updateBuilder.build()

        // delete: gated on current() != nil; optional currentChanged trigger.
        var deleteBuilder = RelayCommand.builder()
            .task({ if let c = current() { deleteCurrent(c) } })
            .predicate({ current() != nil })
        if let changed = currentChanged {
            deleteBuilder = deleteBuilder.triggers(changed)
        }
        let remove = deleteBuilder.build()

        innerRelays = [create, update, remove]

        createNewCommand = create
        updateCurrentCommand = confirmUpdate.map { gate in
            ConfirmationDecoratorCommand(update, confirm: gate)
        } ?? update
        deleteCurrentCommand = confirmDelete.map { gate in
            ConfirmationDecoratorCommand(remove, confirm: gate)
        } ?? remove
    }

    /// Dispose the underlying RelayCommands and their trigger subscriptions.
    /// Idempotent: subsequent calls are a no-op.
    ///
    /// Note: `ConfirmationDecoratorCommand` wrappers (when confirm delegates are
    /// supplied) are NOT tracked separately because they hold no subscriptions of
    /// their own — `canExecuteChanged` is a direct passthrough to the inner
    /// RelayCommand's `canExecuteChanged`. The RelayCommand's dispose() tears
    /// down the trigger subscriptions.
    public func dispose() {
        guard !disposed else { return }
        disposed = true
        for cmd in innerRelays { cmd.dispose() }
    }
}
