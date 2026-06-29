using System.Reflection;
using System.Windows.Input;
using FluentAssertions;
using VMx.Components;
using Xunit;

namespace VMx.Tests.Components;

/// <summary>
/// VMX-018: <c>ComponentVMBase</c> built all five built-in RelayCommands (and
/// their status-trigger subscriptions) eagerly in its constructor, four of which
/// are permanently inert on a leaf VM. They are now built lazily on first
/// property access and cached. These tests assert the laziness, the stable-instance
/// caching (forwarding VMs rely on it), and that the preserved status-trigger
/// wiring still fires <c>CanExecuteChanged</c> on lifecycle transitions (VMX-104).
/// </summary>
public class LazyCommandTests
{
    private static ComponentVM NewLeaf() =>
        ComponentVM.Builder().Name("leaf").WithNullServices().Build();

    private static object? PrivateField(object target, string name)
    {
        // The command fields are declared on the ComponentVMBase base type, so
        // walk up from the concrete runtime type to find them.
        for (var t = target.GetType(); t is not null; t = t.BaseType)
        {
            var field = t.GetField(name, BindingFlags.NonPublic | BindingFlags.Instance);
            if (field is not null)
                return field.GetValue(target);
        }

        throw new InvalidOperationException($"Field '{name}' not found.");
    }

    [Fact]
    public void Commands_Are_Not_Built_Until_Accessed()
    {
        var vm = NewLeaf();

        PrivateField(vm, "_selectCommand").Should().BeNull();
        PrivateField(vm, "_selectNextCommand").Should().BeNull();
        PrivateField(vm, "_reconstructCommand").Should().BeNull();

        // Touching one property builds only that command.
        _ = vm.SelectNextCommand;
        PrivateField(vm, "_selectNextCommand").Should().NotBeNull();
        PrivateField(vm, "_selectCommand").Should().BeNull("only the accessed command is built");
    }

    [Fact]
    public void Command_Property_Returns_A_Stable_Cached_Instance()
    {
        var vm = NewLeaf();

        ICommand first = vm.SelectCommand;
        ICommand second = vm.SelectCommand;

        second.Should().BeSameAs(first, "the lazily-built command must be cached");
    }

    [Fact]
    public void Lazily_Built_Command_Still_Fires_CanExecuteChanged_On_Status_Change()
    {
        var vm = NewLeaf();

        var raised = 0;
        vm.SelectCommand.CanExecuteChanged += (_, _) => raised++;

        vm.Construct(); // Constructing -> Constructed: status trigger emits

        raised.Should().BeGreaterThan(0,
            "the lazily-built command keeps its status-trigger wiring (VMX-104)");
    }

    [Fact]
    public void Disposing_Without_Accessing_Commands_Does_Not_Throw()
    {
        var vm = NewLeaf();
        vm.Construct();

        var act = () => vm.Dispose();
        act.Should().NotThrow("un-built (null) command slots must be safe to dispose");
    }
}
