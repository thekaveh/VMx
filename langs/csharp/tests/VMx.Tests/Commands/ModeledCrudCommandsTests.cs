using System.Reactive;
using System.Reactive.Subjects;
using FluentAssertions;
using VMx.Commands;
using Xunit;

namespace VMx.Tests.Commands;

/// <summary>
/// Unit tests for <see cref="ModeledCrudCommands{M,VM}"/> covering disposal
/// and resource cleanup. Conformance tests for create / update / delete
/// behaviour live in VMx.Conformance.Tests under COMP-019..024.
/// </summary>
public class ModeledCrudCommandsTests
{
    [Fact]
    public void Dispose_Is_Idempotent()
    {
        var vm1 = new object();
        var crud = new ModeledCrudCommands<object, object>(
            current: () => vm1,
            createNew: () => { },
            updateCurrent: _ => { },
            deleteCurrent: _ => { });

        // Sanity: commands work before dispose.
        crud.CreateNewCommand.CanExecute(null).Should().BeTrue();
        crud.UpdateCurrentCommand.CanExecute(null).Should().BeTrue();
        crud.DeleteCurrentCommand.CanExecute(null).Should().BeTrue();

        // First and second Dispose calls both succeed.
        var act = () => crud.Dispose();
        act.Should().NotThrow();
        act.Should().NotThrow("Dispose must be idempotent");
    }

    [Fact]
    public void Update_And_Delete_Are_Wrapped_With_Confirmation_When_Configured()
    {
        var vm1 = new object();
        using var crud = new ModeledCrudCommands<object, object>(
            current: () => vm1,
            createNew: () => { },
            updateCurrent: _ => { },
            deleteCurrent: _ => { },
            confirmUpdate: () => Task.FromResult(true),
            confirmDelete: () => Task.FromResult(true));

        crud.UpdateCurrentCommand.Should().BeOfType<ConfirmationDecoratorCommand>();
        crud.DeleteCurrentCommand.Should().BeOfType<ConfirmationDecoratorCommand>();
        crud.CreateNewCommand.Should().NotBeOfType<ConfirmationDecoratorCommand>(
            "createNew has no confirm hook by spec");
        // Exiting the using block triggers Dispose on the wrapped path; the
        // double-dispose check below verifies that path is idempotent too.
        crud.Dispose();
        var second = () => crud.Dispose();
        second.Should().NotThrow("dispose must be idempotent even with confirmation wrappers");
    }

    [Fact]
    public void Update_And_Delete_Raise_CanExecuteChanged_On_CurrentChanged_Trigger()
    {
        // VMX-011: when a current-changed trigger is supplied, the Update/Delete
        // commands must raise CanExecuteChanged on selection change so bound
        // buttons refresh their enabled state instead of going stale.
        object? current = null;
        using var currentChanged = new Subject<Unit>();
        using var crud = new ModeledCrudCommands<object, object>(
            current: () => current,
            createNew: () => { },
            updateCurrent: _ => { },
            deleteCurrent: _ => { },
            currentChanged: currentChanged);

        var updateRaised = 0;
        var deleteRaised = 0;
        crud.UpdateCurrentCommand.CanExecuteChanged += (_, _) => updateRaised++;
        crud.DeleteCurrentCommand.CanExecuteChanged += (_, _) => deleteRaised++;

        // Initially nothing is selected → both disabled.
        crud.UpdateCurrentCommand.CanExecute(null).Should().BeFalse();
        crud.DeleteCurrentCommand.CanExecute(null).Should().BeFalse();

        // Selection changes — the trigger fires; CanExecute flips to enabled.
        current = new object();
        currentChanged.OnNext(Unit.Default);

        updateRaised.Should().BeGreaterThan(0, "Update CanExecuteChanged must fire on current-changed");
        deleteRaised.Should().BeGreaterThan(0, "Delete CanExecuteChanged must fire on current-changed");
        crud.UpdateCurrentCommand.CanExecute(null).Should().BeTrue();
        crud.DeleteCurrentCommand.CanExecute(null).Should().BeTrue();
    }

    [Fact]
    public void CurrentChanged_Trigger_Reaches_Confirmation_Wrapped_Commands()
    {
        // The confirm-wrapped decorator must forward the inner trigger's
        // CanExecuteChanged (VMX-011 + decorator transparency).
        object? current = null;
        using var currentChanged = new Subject<Unit>();
        using var crud = new ModeledCrudCommands<object, object>(
            current: () => current,
            createNew: () => { },
            updateCurrent: _ => { },
            deleteCurrent: _ => { },
            confirmDelete: () => Task.FromResult(true),
            currentChanged: currentChanged);

        var deleteRaised = 0;
        crud.DeleteCurrentCommand.CanExecuteChanged += (_, _) => deleteRaised++;

        current = new object();
        currentChanged.OnNext(Unit.Default);

        deleteRaised.Should().BeGreaterThan(0,
            "the confirmation decorator must forward the inner command's CanExecuteChanged");
    }

    [Fact]
    public void Public_Command_Surface_Remains_Safe_After_Dispose()
    {
        // ModeledCrudCommands creates its inner RelayCommands internally, so
        // we can't intercept their triggers. What we CAN verify is that the
        // public command surface remains safe to call after disposal —
        // event subscription doesn't throw, CanExecute/Execute don't throw,
        // and double-dispose is a no-op. This is the analogue of the
        // Python/TS "completes inner canExecuteChanged" tests, adapted to
        // C# event semantics (events have no "completion" notion; the
        // contract is "always safe to call").
        var vm1 = new object();
        var crud = new ModeledCrudCommands<object, object>(
            current: () => vm1,
            createNew: () => { },
            updateCurrent: _ => { },
            deleteCurrent: _ => { });

        crud.CreateNewCommand.CanExecute(null).Should().BeTrue();
        crud.UpdateCurrentCommand.CanExecute(null).Should().BeTrue();
        crud.DeleteCurrentCommand.CanExecute(null).Should().BeTrue();

        crud.Dispose();

        // Exercise every command's full surface (event subscribe, CanExecute,
        // Execute) post-dispose. This adapts the Python/TS coverage that
        // checks completion on all three command streams to C# event
        // semantics, where the equivalent contract is "always safe to call".
        foreach (var cmd in new[]
                 {
                     crud.CreateNewCommand, crud.UpdateCurrentCommand, crud.DeleteCurrentCommand,
                 })
        {
            var subscribe = () => cmd.CanExecuteChanged += (_, _) => { };
            subscribe.Should().NotThrow();
            var canExecute = () => cmd.CanExecute(null);
            canExecute.Should().NotThrow();
            var execute = () => cmd.Execute(null);
            execute.Should().NotThrow();
        }

        crud.Dispose();  // idempotent
    }
}
