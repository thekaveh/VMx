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
        // Execute) post-dispose to mirror the Python/TS sub_a/sub_b/sub_c
        // coverage that verifies completion on all three streams.
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
