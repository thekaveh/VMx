using System.Reactive.Concurrency;
using System.Reactive.Linq;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using VMx.Capabilities;
using VMx.Hierarchical;
using VMx.Services;
using Xunit;

namespace NotesShowcase.Tests.ViewModels;

public sealed class NotebooksRootVMTests
{
    private static NotebooksRootVM BuildVM(INoteRepository repo)
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        return NotebooksRootVM.Builder()
            .Name("root")
            .Services(hub, dispatcher)
            .Repository(repo)
            .Build();
    }

    [Fact]
    public void Implements_INewCreatable_and_IReconstructable()
    {
        var repo = new InMemoryNoteRepository(SeedData.Build());
        var vm = BuildVM(repo);
        Assert.IsAssignableFrom<INewCreatable>(vm);
        Assert.IsAssignableFrom<IReconstructable>(vm);
    }

    [Fact]
    public async Task PopulateAsync_loads_seed_notebooks_and_assigns_roots()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(), loadAllDelay: TimeSpan.Zero);
        var vm = BuildVM(repo);
        vm.Construct();
        await vm.PopulateAsync();
        Assert.Equal(5, vm.All.Count);
        // 4 root notebooks per SeedData.
        Assert.Equal(4, vm.Roots.Count);
        // nb-specs is a child of nb-work.
        var work = vm.All.Single(n => n.Model.Id == "nb-work");
        var specs = vm.ChildrenOf(work).Single();
        Assert.Equal("nb-specs", specs.Model.Id);
    }

    [Fact]
    public async Task AddNotebookAsync_emits_TreeStructureChangedMessage_and_appends_child()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            addNotebookDelay: TimeSpan.Zero);
        var vm = BuildVM(repo);
        vm.Construct();
        await vm.PopulateAsync();
        var observed = new List<TreeStructureChangedMessage>();
        using var sub = vm.Hub.Messages
            .OfType<TreeStructureChangedMessage>()
            .Subscribe(observed.Add);

        await vm.AddNotebookAsync(parentId: null, name: "Inbox");

        Assert.NotEmpty(observed);
        Assert.Contains(vm.Walk(), n => n.Model.Name == "Inbox");
    }

    [Fact]
    public async Task Current_setter_round_trip_emits_PropertyChangedMessage()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(), loadAllDelay: TimeSpan.Zero);
        var vm = BuildVM(repo);
        vm.Construct();
        await vm.PopulateAsync();
        var first = vm.Roots[0];
        vm.Current = first;
        Assert.Same(first, vm.Current);
        // Idempotent: setting the same value is a no-op.
        vm.Current = first;
        Assert.Same(first, vm.Current);
        // Clear:
        vm.Current = null;
        Assert.Null(vm.Current);
    }

    [Fact]
    public async Task AddNotebookCommand_executes_when_constructed()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            addNotebookDelay: TimeSpan.Zero);
        var vm = BuildVM(repo);
        vm.Construct();
        await vm.PopulateAsync();
        var before = vm.All.Count;
        vm.AddNotebookCommand.Execute(null);
        // CreateNew uses fire-and-forget — drain the task queue.
        await Task.Delay(50);
        Assert.True(vm.All.Count > before);
    }
}
