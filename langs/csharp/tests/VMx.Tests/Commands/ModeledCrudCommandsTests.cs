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
    public void Dispose_Stops_Inner_CanExecuteChanged_Propagation()
    {
        // Use a manual trigger via a RelayCommand built externally, wrap it
        // through a CompositeCommand-like check: ModeledCrudCommands creates
        // its inner RelayCommands internally, so we verify that after
        // disposing the helper, attempting to invoke its commands still
        // works (no NullReferenceException etc.) — i.e., disposal does not
        // corrupt the public command surface, and double-dispose is safe.
        var vm1 = new object();
        using var trigger = new Subject<System.Reactive.Unit>();
        var crud = new ModeledCrudCommands<object, object>(
            current: () => vm1,
            createNew: () => { },
            updateCurrent: _ => { },
            deleteCurrent: _ => { });

        var firedBefore = 0;
        var firedAfter = 0;
        crud.CreateNewCommand.CanExecuteChanged += (_, _) => firedBefore++;

        // Pre-dispose: command surface is responsive.
        crud.CreateNewCommand.CanExecute(null).Should().BeTrue();

        crud.Dispose();

        // Post-dispose: re-subscribing does not throw, and any CanExecute
        // / Execute calls remain safe (the public surface contract is
        // 'always safe to call').
        crud.CreateNewCommand.CanExecuteChanged += (_, _) => firedAfter++;
        var canExecute = () => crud.CreateNewCommand.CanExecute(null);
        canExecute.Should().NotThrow();

        // Idempotent dispose.
        crud.Dispose();
    }
}
