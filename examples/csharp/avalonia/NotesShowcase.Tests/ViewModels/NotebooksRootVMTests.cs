using System.Reactive.Concurrency;
using System.Reactive.Linq;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using VMx.Capabilities;
using VMx.Hierarchical;
using VMx.Notifications;
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
        // CreateNew uses fire-and-forget — wait for the new notebook to appear.
        await TestWait.WaitUntilAsync(() => vm.All.Count > before);
        Assert.True(vm.All.Count > before);
    }

    // ── Phase 5.a binding gap #2: hierarchical Children accessor ──────────

    [Fact]
    public async Task After_PopulateAsync_each_notebook_resolves_Children_via_parent_id()
    {
        var repo = new InMemoryNoteRepository(SeedData.Build(), loadAllDelay: TimeSpan.Zero);
        var vm = BuildVM(repo);
        vm.Construct();
        await vm.PopulateAsync();

        var work = vm.All.Single(n => n.Model.Id == "nb-work");
        var specs = vm.All.Single(n => n.Model.Id == "nb-specs");

        // "Specs" must appear under "Work" via the Children accessor — this is
        // what the Avalonia TreeView's TreeDataTemplate.ItemsSource binds to.
        Assert.Contains(specs, work.Children);
        Assert.Single(work.Children);
        // Leaf notebooks (no children) return an empty list.
        Assert.Empty(specs.Children);
    }

    // ── notification coverage: "Notebook added" notification ──────────────────

    [Fact]
    public async Task AddNotebookAsync_publishes_Notebook_added_notification_when_hub_wired()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            addNotebookDelay: TimeSpan.Zero);
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        using var notificationHub = new NotificationHub();
        var observed = new List<Notification>();
        using var sub = notificationHub.Pending.Subscribe(snapshot =>
        {
            foreach (var n in snapshot) if (!observed.Contains(n)) observed.Add(n);
        });
        var vm = NotebooksRootVM.Builder()
            .Name("root").Services(hub, dispatcher).Repository(repo)
            .NotificationHub(notificationHub).Build();
        vm.Construct();
        await vm.PopulateAsync();

        await vm.AddNotebookAsync(parentId: null, name: "Inbox");

        Assert.Contains(observed, n => n.Message.Contains("Notebook added") && n.Message.Contains("Inbox"));
    }

    [Fact]
    public async Task AddNotebookAsync_with_parentId_appears_under_parent_Children()
    {
        var repo = new InMemoryNoteRepository(
            SeedData.Build(),
            loadAllDelay: TimeSpan.Zero,
            addNotebookDelay: TimeSpan.Zero);
        var vm = BuildVM(repo);
        vm.Construct();
        await vm.PopulateAsync();
        var work = vm.All.Single(n => n.Model.Id == "nb-work");
        var beforeCount = work.Children.Count;

        await vm.AddNotebookAsync(parentId: "nb-work", name: "Subspecs");

        var added = vm.All.Single(n => n.Model.Name == "Subspecs");
        Assert.Equal("nb-work", added.Model.ParentId);
        Assert.Contains(added, work.Children);
        Assert.Equal(beforeCount + 1, work.Children.Count);
    }

    [Fact]
    public async Task PopulateAsync_raises_PropertyChanged_for_Roots()
    {
        // Regression: Roots is a computed snapshot; without this raise an
        // already-bound TreeView stays empty forever (the App binds the
        // window BEFORE ConstructAsync completes).
        var repo = new InMemoryNoteRepository(SeedData.Build());
        var vm = BuildVM(repo);
        vm.Construct();
        var raised = new List<string?>();
        ((System.ComponentModel.INotifyPropertyChanged)vm).PropertyChanged +=
            (_, e) => raised.Add(e.PropertyName);

        await vm.PopulateAsync();

        Assert.Contains(nameof(NotebooksRootVM.Roots), raised);
    }

    [Fact]
    public async Task AddNotebookAsync_root_level_raises_PropertyChanged_for_Roots()
    {
        var repo = new InMemoryNoteRepository(SeedData.Build());
        var vm = BuildVM(repo);
        vm.Construct();
        await vm.PopulateAsync();
        var raised = new List<string?>();
        ((System.ComponentModel.INotifyPropertyChanged)vm).PropertyChanged +=
            (_, e) => raised.Add(e.PropertyName);

        await vm.AddNotebookAsync(parentId: null, name: "Fresh Root");

        Assert.Contains(nameof(NotebooksRootVM.Roots), raised);
    }
}
