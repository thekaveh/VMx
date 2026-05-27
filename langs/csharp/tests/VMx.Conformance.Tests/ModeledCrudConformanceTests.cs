using FluentAssertions;
using VMx.Commands;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// Conformance tests for modeled CRUD commands, COMP-019..024.
/// See spec/06-composite-vm.md §Modeled CRUD and ADR-0016.
/// </summary>
public class ModeledCrudConformanceTests
{
    [Fact, Trait("Conformance", "COMP-019")]
    public void COMP_019_CreateNew_Invokes_Action()
    {
        var log = new List<string>();
        using var crud = new ModeledCrudCommands<object, object>(
            current: () => null,
            createNew: () => log.Add("create"),
            updateCurrent: _ => { },
            deleteCurrent: _ => { });
        crud.CreateNewCommand.Execute(null);
        log.Should().Equal("create");
    }

    [Fact, Trait("Conformance", "COMP-020")]
    public void COMP_020_UpdateCurrent_Invokes_With_Current()
    {
        var log = new List<object>();
        var vm1 = new object();
        using var crud = new ModeledCrudCommands<object, object>(
            current: () => vm1,
            createNew: () => { },
            updateCurrent: log.Add,
            deleteCurrent: _ => { });
        crud.UpdateCurrentCommand.Execute(null);
        log.Should().Equal(vm1);
    }

    [Fact, Trait("Conformance", "COMP-021")]
    public void COMP_021_Update_CanExecute_False_When_Current_Null()
    {
        using var crud = new ModeledCrudCommands<object, object>(
            current: () => null,
            createNew: () => { },
            updateCurrent: _ => { },
            deleteCurrent: _ => { });
        crud.UpdateCurrentCommand.CanExecute(null).Should().BeFalse();
    }

    [Fact, Trait("Conformance", "COMP-022")]
    public void COMP_022_DeleteCurrent_Invokes_With_Current()
    {
        var log = new List<object>();
        var vm1 = new object();
        using var crud = new ModeledCrudCommands<object, object>(
            current: () => vm1,
            createNew: () => { },
            updateCurrent: _ => { },
            deleteCurrent: log.Add);
        crud.DeleteCurrentCommand.Execute(null);
        log.Should().Equal(vm1);
    }

    [Fact, Trait("Conformance", "COMP-023")]
    public void COMP_023_Delete_CanExecute_False_When_Current_Null()
    {
        using var crud = new ModeledCrudCommands<object, object>(
            current: () => null,
            createNew: () => { },
            updateCurrent: _ => { },
            deleteCurrent: _ => { });
        crud.DeleteCurrentCommand.CanExecute(null).Should().BeFalse();
    }

    [Fact, Trait("Conformance", "COMP-024")]
    public async Task COMP_024_Delete_Confirm_Gate()
    {
        var log = new List<object>();
        var vm1 = new object();

        using var crudNo = new ModeledCrudCommands<object, object>(
            current: () => vm1,
            createNew: () => { },
            updateCurrent: _ => { },
            deleteCurrent: log.Add,
            confirmDelete: () => Task.FromResult(false));
        var confDelete = crudNo.DeleteCurrentCommand as ConfirmationDecoratorCommand;
        confDelete.Should().NotBeNull();
        await confDelete!.ExecuteAsync(null);
        log.Should().BeEmpty();

        using var crudYes = new ModeledCrudCommands<object, object>(
            current: () => vm1,
            createNew: () => { },
            updateCurrent: _ => { },
            deleteCurrent: log.Add,
            confirmDelete: () => Task.FromResult(true));
        var confDelete2 = crudYes.DeleteCurrentCommand as ConfirmationDecoratorCommand;
        await confDelete2!.ExecuteAsync(null);
        log.Should().Equal(vm1);
    }
}
