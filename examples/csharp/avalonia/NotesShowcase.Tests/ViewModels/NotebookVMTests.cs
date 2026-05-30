using System.Reactive.Concurrency;
using System.Reactive.Linq;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using VMx.Capabilities;
using VMx.Components;
using VMx.Messages;
using VMx.Services;
using Xunit;

namespace NotesShowcase.Tests.ViewModels;

public sealed class NotebookVMTests
{
    private static NotebookVM Build(string id = "id-1", string name = "Work", bool initiallyExpanded = false)
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        return NotebookVM.Builder()
            .Name("nb")
            .Services(hub, dispatcher)
            .Model(new NotebookModel(id, name, null))
            .InitiallyExpanded(initiallyExpanded)
            .Build();
    }

    [Fact]
    public void Capability_set_is_exactly_the_five_declared_interfaces()
    {
        var vm = Build();
        // Declared capabilities (plan §3.a.6 + scenario §6.2):
        Assert.IsAssignableFrom<ISelectable>(vm);
        Assert.IsAssignableFrom<IExpandable>(vm);
        Assert.IsAssignableFrom<ICollapsible>(vm);
        Assert.IsAssignableFrom<IExpansionTogglable>(vm);
        Assert.IsAssignableFrom<IReconstructable>(vm);
        // Capabilities NOT applicable to a notebook:
        Assert.IsNotAssignableFrom<IClosable>(vm);
        Assert.IsNotAssignableFrom<INewCreatable>(vm);
        Assert.IsNotAssignableFrom<IDeletable<NotebookVM>>(vm);
    }

    [Fact]
    public void ToggleExpansion_emits_IsExpanded_PropertyChangedMessage()
    {
        var vm = Build();
        vm.Construct();
        var observed = new List<string>();
        using var sub = vm.Hub.Messages
            .OfType<PropertyChangedMessage<IComponentVM>>()
            .Subscribe(m => observed.Add(m.PropertyName));

        vm.ToggleExpansion();

        Assert.Contains(nameof(NotebookVM.IsExpanded), observed);
        Assert.True(vm.IsExpanded);
    }

    [Fact]
    public void Setting_Model_emits_Model_and_NotebookName_PropertyChangedMessages()
    {
        var vm = Build(name: "Old Name");
        vm.Construct();
        var observed = new List<string>();
        using var sub = vm.Hub.Messages
            .OfType<PropertyChangedMessage<IComponentVM>>()
            .Subscribe(m => observed.Add(m.PropertyName));

        vm.Model = new NotebookModel(vm.Model.Id, "New Name", vm.Model.ParentId);

        Assert.Contains(nameof(NotebookVM.Model), observed);
        Assert.Contains(nameof(NotebookVM.NotebookName), observed);
        Assert.Equal("New Name", vm.NotebookName);
    }

    [Fact]
    public void Setting_Model_to_equal_value_is_a_no_op_no_messages()
    {
        var vm = Build(name: "Same");
        vm.Construct();
        var observed = new List<string>();
        using var sub = vm.Hub.Messages
            .OfType<PropertyChangedMessage<IComponentVM>>()
            .Subscribe(m => observed.Add(m.PropertyName));

        vm.Model = vm.Model with { };

        Assert.DoesNotContain(nameof(NotebookVM.Model), observed);
    }

    [Fact]
    public void Expand_and_Collapse_predicates_track_state()
    {
        var vm = Build(initiallyExpanded: false);
        vm.Construct();

        Assert.True(vm.CanExpand());
        Assert.False(vm.CanCollapse());
        vm.Expand();
        Assert.True(vm.IsExpanded);
        Assert.False(vm.CanExpand());
        Assert.True(vm.CanCollapse());
        vm.Collapse();
        Assert.False(vm.IsExpanded);
        // Idempotent: re-collapse is a no-op.
        vm.Collapse();
        Assert.False(vm.IsExpanded);
    }

    [Fact]
    public void Dispose_disposes_expandable_state_and_clears_status()
    {
        var vm = Build();
        vm.Construct();
        vm.Dispose();
        Assert.Equal(VMx.Lifecycle.ConstructionStatus.Disposed, vm.Status);
    }
}
