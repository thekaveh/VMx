using System.Collections;
using System.Collections.ObjectModel;
using System.Collections.Specialized;
using System.Reactive.Concurrency;
using NotesShowcase.Models;
using NotesShowcase.ViewModels;
using NotesShowcase.Views.Adapter;
using VMx.Composites;
using VMx.Services;
using Xunit;

namespace NotesShowcase.Tests.Views.Adapter;

/// <summary>
/// Adapter contract (plan §4.a, scenario §7.1 CollectionBridge): wraps a VMx
/// <see cref="ICompositeVM{VM}"/> source and mirrors its add/remove/replace
/// mutations on the base <see cref="ObservableCollection{T}"/> so XAML
/// ItemsControl can subscribe to standard INCC events.
/// </summary>
public sealed class ObservableCollectionBridgeTests
{
    private static (MessageHub hub, IDispatcher dispatcher) BuildServices()
    {
        var hub = new MessageHub();
        var dispatcher = new RxDispatcher(ImmediateScheduler.Instance, ImmediateScheduler.Instance);
        return (hub, dispatcher);
    }

    private static NoteVM BuildNote(MessageHub hub, IDispatcher dispatcher, string id)
    {
        var model = new NoteModel(id, "nb", id, Array.Empty<string>(), "", false,
            DateTimeOffset.UtcNow, DateTimeOffset.UtcNow);
        var vm = NoteVM.Builder().Name(id).Services(hub, dispatcher).Model(model).Build();
        vm.Construct();
        return vm;
    }

    private static CompositeVM<NoteVM> BuildSource(MessageHub hub, IDispatcher dispatcher)
    {
        var src = CompositeVM<NoteVM>.Builder()
            .Name("notes")
            .Services(hub, dispatcher)
            .Children(() => Array.Empty<NoteVM>())
            .Build();
        src.Construct();
        return src;
    }

    [Fact]
    public void Initial_snapshot_mirrors_source_at_construction_time()
    {
        var (hub, dispatcher) = BuildServices();
        var src = BuildSource(hub, dispatcher);
        var n1 = BuildNote(hub, dispatcher, "n1");
        var n2 = BuildNote(hub, dispatcher, "n2");
        src.Add(n1);
        src.Add(n2);

        using var bridge = new ObservableCollectionBridge<NoteVM>(src);

        Assert.Equal(2, bridge.Count);
        Assert.Same(n1, bridge[0]);
        Assert.Same(n2, bridge[1]);
    }

    [Fact]
    public void Add_on_source_emits_INCC_Add_with_correct_index_and_item()
    {
        var (hub, dispatcher) = BuildServices();
        var src = BuildSource(hub, dispatcher);
        using var bridge = new ObservableCollectionBridge<NoteVM>(src);

        var events = new List<NotifyCollectionChangedEventArgs>();
        bridge.CollectionChanged += (_, e) => events.Add(e);

        var n1 = BuildNote(hub, dispatcher, "n1");
        src.Add(n1);

        var add = Assert.Single(events);
        Assert.Equal(NotifyCollectionChangedAction.Add, add.Action);
        Assert.Equal(0, add.NewStartingIndex);
        Assert.Same(n1, add.NewItems![0]);
        Assert.Same(n1, bridge[0]);
    }

    [Fact]
    public void Remove_on_source_emits_INCC_Remove_with_correct_index_and_item()
    {
        var (hub, dispatcher) = BuildServices();
        var src = BuildSource(hub, dispatcher);
        var n1 = BuildNote(hub, dispatcher, "n1");
        var n2 = BuildNote(hub, dispatcher, "n2");
        src.Add(n1);
        src.Add(n2);

        using var bridge = new ObservableCollectionBridge<NoteVM>(src);

        var events = new List<NotifyCollectionChangedEventArgs>();
        bridge.CollectionChanged += (_, e) => events.Add(e);

        src.RemoveAt(0);

        var remove = Assert.Single(events);
        Assert.Equal(NotifyCollectionChangedAction.Remove, remove.Action);
        Assert.Equal(0, remove.OldStartingIndex);
        Assert.Same(n1, remove.OldItems![0]);
        Assert.Single(bridge);
        Assert.Same(n2, bridge[0]);
    }

    [Fact]
    public void Replace_on_source_is_mirrored_on_bridge()
    {
        var (hub, dispatcher) = BuildServices();
        var src = BuildSource(hub, dispatcher);
        var n1 = BuildNote(hub, dispatcher, "n1");
        var n2 = BuildNote(hub, dispatcher, "n2");
        src.Add(n1);

        using var bridge = new ObservableCollectionBridge<NoteVM>(src);

        // The source raises Replace as a Remove + Add pair (per CompositeVMBase
        // §IList[int].set). We assert the final state mirrors the replacement.
        src[0] = n2;

        Assert.Single(bridge);
        Assert.Same(n2, bridge[0]);
    }

    [Fact]
    public void Dispose_unsubscribes_from_source_CollectionChanged()
    {
        var (hub, dispatcher) = BuildServices();
        var src = BuildSource(hub, dispatcher);
        var bridge = new ObservableCollectionBridge<NoteVM>(src);

        var events = new List<NotifyCollectionChangedEventArgs>();
        bridge.CollectionChanged += (_, e) => events.Add(e);

        bridge.Dispose();

        src.Add(BuildNote(hub, dispatcher, "n1"));

        Assert.Empty(events);
    }

    [Fact]
    public void Constructor_rejects_null_source()
    {
        Assert.Throws<ArgumentNullException>(() => new ObservableCollectionBridge<NoteVM>(null!));
    }

    [Fact]
    public void Constructor_rejects_source_that_is_not_IEnumerable_of_T()
    {
        // INCC source whose IEnumerable element type does not match T.
        var src = new ObservableCollection<string>();
        Assert.Throws<ArgumentException>(() => new ObservableCollectionBridge<NoteVM>(src));
    }

    [Fact]
    public void Replace_action_on_source_is_mirrored_directly()
    {
        // Use a plain ObservableCollection<int> driver — its set indexer raises
        // a true Replace event (unlike CompositeVMBase, which raises Remove+Add).
        var src = new ObservableCollection<int> { 10, 20, 30 };
        using var bridge = new ObservableCollectionBridge<int>(src);

        src[1] = 99;

        Assert.Equal(new[] { 10, 99, 30 }, bridge);
    }

    [Fact]
    public void Move_action_on_source_is_mirrored_directly()
    {
        var src = new ObservableCollection<int> { 1, 2, 3 };
        using var bridge = new ObservableCollectionBridge<int>(src);

        src.Move(0, 2);

        Assert.Equal(new[] { 2, 3, 1 }, bridge);
    }

    [Fact]
    public void Reset_action_on_source_triggers_full_resync_from_snapshot()
    {
        var src = new ManualIncc<int> { 1, 2, 3 };
        using var bridge = new ObservableCollectionBridge<int>(src);

        // Drop everything in the source, then raise Reset.
        src.ResetTo(new[] { 7, 8, 9 });

        Assert.Equal(new[] { 7, 8, 9 }, bridge);
    }

    [Fact]
    public void Multi_item_Add_is_mirrored_with_correct_starting_index()
    {
        var src = new ManualIncc<int> { 1 };
        using var bridge = new ObservableCollectionBridge<int>(src);

        src.RaiseAdd(new[] { 2, 3, 4 }, startingIndex: 1);

        Assert.Equal(new[] { 1, 2, 3, 4 }, bridge);
    }

    [Fact]
    public void Remove_without_source_index_falls_back_to_full_resync()
    {
        var src = new ManualIncc<int> { 1, 2, 3 };
        using var bridge = new ObservableCollectionBridge<int>(src);

        src.RaiseRemoveWithoutIndex(2);

        Assert.Equal(new[] { 1, 3 }, bridge);
    }

    /// <summary>
    /// Minimal INCC + IList&lt;T&gt; source that lets tests fire arbitrary
    /// <see cref="NotifyCollectionChangedEventArgs"/> actions (including
    /// multi-item Add, Reset, Move) without going through
    /// <see cref="CompositeVMBase{T}"/>'s mutation semantics.
    /// </summary>
    private sealed class ManualIncc<T> : List<T>, INotifyCollectionChanged
    {
        public event NotifyCollectionChangedEventHandler? CollectionChanged;

        public void RaiseAdd(IList<T> items, int startingIndex)
        {
            for (var i = 0; i < items.Count; i++)
                Insert(startingIndex + i, items[i]);
            CollectionChanged?.Invoke(this,
                new NotifyCollectionChangedEventArgs(
                    NotifyCollectionChangedAction.Add, (IList)items, startingIndex));
        }

        public void ResetTo(IEnumerable<T> next)
        {
            Clear();
            AddRange(next);
            CollectionChanged?.Invoke(this,
                new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Reset));
        }

        public void RaiseRemoveWithoutIndex(T item)
        {
            Remove(item);
            CollectionChanged?.Invoke(this,
                new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Remove, item));
        }
    }
}
