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
    public void Dispose_Wraps_Update_And_Delete_With_Confirmation_When_Configured()
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
        // Exiting the using block calls Dispose; verify no exception (idempotence
        // for the wrapped path is covered by Dispose_Is_Idempotent above).
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
        crud.Dispose();

        var subscribe = () => crud.CreateNewCommand.CanExecuteChanged += (_, _) => { };
        subscribe.Should().NotThrow();
        var canExecute = () => crud.CreateNewCommand.CanExecute(null);
        canExecute.Should().NotThrow();
        var executeNoOp = () => crud.UpdateCurrentCommand.Execute(null);
        executeNoOp.Should().NotThrow();

        crud.Dispose();  // idempotent
    }
}
