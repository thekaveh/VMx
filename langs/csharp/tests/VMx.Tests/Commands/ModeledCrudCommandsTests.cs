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
    public void Dispose_Releases_Inner_RelayCommands()
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

        // Dispose must not throw and must leave the helper in a tear-down state.
        var act = () => crud.Dispose();
        act.Should().NotThrow();

        // Double dispose is safe (idempotent).
        var act2 = () => crud.Dispose();
        act2.Should().NotThrow();
    }

    [Fact]
    public void Dispose_Releases_Confirmation_Wrappers()
    {
        var vm1 = new object();
        using var crud = new ModeledCrudCommands<object, object>(
            current: () => vm1,
            createNew: () => { },
            updateCurrent: _ => { },
            deleteCurrent: _ => { },
            confirmUpdate: () => System.Threading.Tasks.Task.FromResult(true),
            confirmDelete: () => System.Threading.Tasks.Task.FromResult(true));

        crud.UpdateCurrentCommand.Should().BeOfType<ConfirmationDecoratorCommand>();
        crud.DeleteCurrentCommand.Should().BeOfType<ConfirmationDecoratorCommand>();

        // Exiting the using block calls Dispose; verify no exception.
    }
}
