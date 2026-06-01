using System.Collections.Specialized;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Composites;

/// <summary>
/// Unit tests for <see cref="CompositeVM{VM}"/> (non-modeled variant).
/// Conformance-level tests live in VMx.Conformance.Tests.
/// </summary>
public class CompositeVMTests
{
    // ── Factory helpers ──────────────────────────────────────────────────────

    private static (CompositeVM<ComponentVM<string>> composite, TestHub hub, TestDispatcher dispatcher)
        BuildComposite(string name = "root", bool asyncSelection = false)
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name(name)
            .Services(hub, dispatcher)
            .AsyncSelection(asyncSelection)
            .Children(() => Array.Empty<ComponentVM<string>>())
            .Build();
        return (composite, hub, dispatcher);
    }

    private static ComponentVM<string> BuildChild(TestHub hub, TestDispatcher dispatcher, string name = "child1")
        => ComponentVM<string>.Builder()
            .Name(name).Services(hub, dispatcher).Model("m").Build();

    // ── Type and identity ────────────────────────────────────────────────────

    [Fact]
    public void Type_Is_Composite()
    {
        var (composite, _, _) = BuildComposite();
        composite.Type.Should().Be(ViewModelType.Composite);
    }

    [Fact]
    public void Name_Is_Set_From_Builder()
    {
        var (composite, _, _) = BuildComposite("root");
        composite.Name.Should().Be("root");
    }

    [Fact]
    public void Initial_Count_Is_Zero()
    {
        var (composite, _, _) = BuildComposite();
        composite.Count.Should().Be(0);
    }

    [Fact]
    public void Initial_Current_Is_Null()
    {
        var (composite, _, _) = BuildComposite();
        composite.Current.Should().BeNull();
    }

    // ── IList<VM>: Add ───────────────────────────────────────────────────────

    [Fact]
    public void Add_Increases_Count()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Count.Should().Be(1);
    }

    [Fact]
    public void Add_Sets_Child_Parent()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        child.Parent.Should().BeSameAs(composite);
    }

    [Fact]
    public void Add_Emits_CollectionChanged_Add()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        NotifyCollectionChangedEventArgs? evt = null;
        composite.CollectionChanged += (_, e) => evt = e;

        composite.Add(child);

        evt.Should().NotBeNull();
        evt!.Action.Should().Be(NotifyCollectionChangedAction.Add);
        evt.NewItems.Should().NotBeNull();
        evt.NewItems![0].Should().BeSameAs(child);
        evt.NewStartingIndex.Should().Be(0);
    }

    // ── IList<VM>: Remove ────────────────────────────────────────────────────

    [Fact]
    public void Remove_Decreases_Count()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Remove(child);
        composite.Count.Should().Be(0);
    }

    [Fact]
    public void Remove_Clears_Child_Parent()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Remove(child);
        child.Parent.Should().BeNull();
    }

    [Fact]
    public void Remove_Emits_CollectionChanged_Remove()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        NotifyCollectionChangedEventArgs? evt = null;
        composite.CollectionChanged += (_, e) => evt = e;

        composite.Remove(child);

        evt.Should().NotBeNull();
        evt!.Action.Should().Be(NotifyCollectionChangedAction.Remove);
        evt.OldItems![0].Should().BeSameAs(child);
        evt.OldStartingIndex.Should().Be(0);
    }

    [Fact]
    public void Remove_Returns_False_For_Missing_Item()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Remove(child).Should().BeFalse();
    }

    // ── IList<VM>: Insert ────────────────────────────────────────────────────

    [Fact]
    public void Insert_At_Index_Emits_CollectionChanged()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        composite.Add(c1);

        NotifyCollectionChangedEventArgs? evt = null;
        composite.CollectionChanged += (_, e) => evt = e;
        composite.Insert(0, c2);

        composite[0].Should().BeSameAs(c2);
        composite[1].Should().BeSameAs(c1);
        evt!.Action.Should().Be(NotifyCollectionChangedAction.Add);
        evt.NewStartingIndex.Should().Be(0);
    }

    // ── IList<VM>: Clear ─────────────────────────────────────────────────────

    [Fact]
    public void Clear_Removes_All_Items_And_Emits_Reset()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        composite.Add(BuildChild(hub, dispatcher, "c1"));
        composite.Add(BuildChild(hub, dispatcher, "c2"));
        NotifyCollectionChangedEventArgs? evt = null;
        composite.CollectionChanged += (_, e) => evt = e;

        composite.Clear();

        composite.Count.Should().Be(0);
        evt!.Action.Should().Be(NotifyCollectionChangedAction.Reset);
    }

    [Fact]
    public void Clear_When_Child_Is_Current_Clears_IsCurrent_And_Fires_Hub_Message()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();
        composite.Current = child;

        var propChangedNames = new List<string>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm)
                propChangedNames.Add(pcm.PropertyName);
        });
        var raisedProps = new List<string>();
        ((System.ComponentModel.INotifyPropertyChanged)composite).PropertyChanged += (_, e) =>
        {
            if (e.PropertyName is not null) raisedProps.Add(e.PropertyName);
        };

        composite.Clear();

        child.IsCurrent.Should().BeFalse("Clear must deselect the previously-current child");
        composite.Current.Should().BeNull();
        raisedProps.Should().Contain("Current", "PropertyChanged(\"Current\") must fire");
        propChangedNames.Should().Contain("Current", "hub must publish PropertyChangedMessage for \"Current\"");
    }

    // ── Current / Selection ──────────────────────────────────────────────────

    [Fact]
    public void Current_Can_Be_Set_To_Child()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();

        composite.Current = child;

        composite.Current.Should().BeSameAs(child);
    }

    [Fact]
    public void Current_Set_Updates_IsCurrent_On_Child()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();

        composite.Current = child;

        child.IsCurrent.Should().BeTrue();
    }

    [Fact]
    public void Current_Set_Clears_IsCurrent_On_Previous()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        composite.Add(c1);
        composite.Add(c2);
        composite.Construct();

        composite.Current = c1;
        composite.Current = c2;

        c1.IsCurrent.Should().BeFalse();
        c2.IsCurrent.Should().BeTrue();
    }

    [Fact]
    public void Current_Set_To_Null_Is_Legal()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();
        composite.Current = child;

        composite.Current = null;

        composite.Current.Should().BeNull();
        child.IsCurrent.Should().BeFalse();
    }

    [Fact]
    public void Current_Set_To_Non_Child_Raises()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        composite.Construct();
        var foreign = BuildChild(hub, dispatcher, "foreign");

        var act = () => composite.Current = foreign;

        act.Should().Throw<InvalidOperationException>();
    }

    [Fact]
    public void Current_Set_Emits_PropertyChangedMessage_On_Hub()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();

        var propMessages = new List<string>();
        hub.Messages.Subscribe(m =>
        {
            if (m is IPropertyChangedMessage<IComponentVM> pcm)
                propMessages.Add(pcm.PropertyName);
        });

        composite.Current = child;

        propMessages.Should().Contain("Current");
    }

    // ── SelectComponent / DeselectComponent / CanSelectComponent ────────────

    [Fact]
    public void SelectComponent_Sets_Current()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();

        composite.SelectComponent(child);

        composite.Current.Should().BeSameAs(child);
    }

    [Fact]
    public void SelectComponent_Raises_When_CanSelect_False()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var foreign = BuildChild(hub, dispatcher, "foreign");
        composite.Construct();

        var act = () => composite.SelectComponent(foreign);

        act.Should().Throw<InvalidOperationException>();
    }

    [Fact]
    public void DeselectComponent_Clears_Current()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();
        composite.Current = child;

        composite.DeselectComponent(child);

        composite.Current.Should().BeNull();
    }

    [Fact]
    public void DeselectComponent_Raises_When_Not_Current()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        composite.Add(c1);
        composite.Add(c2);
        composite.Construct();
        composite.Current = c1;

        var act = () => composite.DeselectComponent(c2);

        act.Should().Throw<InvalidOperationException>();
        composite.Current.Should().BeSameAs(c1);
    }

    [Fact]
    public void CanSelectComponent_True_For_Constructed_Child()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();

        composite.CanSelectComponent(child).Should().BeTrue();
    }

    [Fact]
    public void CanSelectComponent_False_For_Non_Child()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var foreign = BuildChild(hub, dispatcher, "foreign");
        composite.Construct();

        composite.CanSelectComponent(foreign).Should().BeFalse();
    }

    [Fact]
    public void CanSelectComponent_False_For_Unconstructed_Child()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        // Composite is NOT constructed — child remains Destructed.

        composite.CanSelectComponent(child).Should().BeFalse();
    }

    // ── Lifecycle: Construct ─────────────────────────────────────────────────

    [Fact]
    public void Construct_With_Children_Factory_Populates_And_Constructs_Children()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var composite = CompositeVM<ComponentVM<string>>.Builder()
            .Name("root")
            .Services(hub, dispatcher)
            .Children(() =>
            [
                BuildChild(hub, dispatcher, "c1"),
                BuildChild(hub, dispatcher, "c2"),
            ])
            .Build();

        composite.Construct();

        composite.Count.Should().Be(2);
        composite[0].Status.Should().Be(ConstructionStatus.Constructed);
        composite[1].Status.Should().Be(ConstructionStatus.Constructed);
        composite.Status.Should().Be(ConstructionStatus.Constructed);
    }

    // ── Lifecycle: Destruct ──────────────────────────────────────────────────

    [Fact]
    public void Destruct_Sets_Current_To_Null_First()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();
        composite.Current = child;

        composite.Destruct();

        composite.Current.Should().BeNull();
        composite.Status.Should().Be(ConstructionStatus.Destructed);
    }

    [Fact]
    public void Destruct_Destructs_All_Children()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        composite.Add(c1);
        composite.Add(c2);
        composite.Construct();

        composite.Destruct();

        c1.Status.Should().Be(ConstructionStatus.Destructed);
        c2.Status.Should().Be(ConstructionStatus.Destructed);
    }

    // ── Lifecycle: Dispose cascade (LIFE-013) ────────────────────────────────

    [Fact]
    public void Dispose_Disposes_All_Children()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        composite.Add(c1);
        composite.Add(c2);
        composite.Construct();

        composite.Dispose();

        c1.Status.Should().Be(ConstructionStatus.Disposed);
        c2.Status.Should().Be(ConstructionStatus.Disposed);
        composite.Status.Should().Be(ConstructionStatus.Disposed);
    }

    // ── AsyncSelection ───────────────────────────────────────────────────────

    [Fact]
    public void AsyncSelection_Does_Not_Change_Current_Synchronously()
    {
        var (composite, hub, dispatcher) = BuildComposite(asyncSelection: true);
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();

        composite.SelectComponent(child);

        // Before advancing the scheduler: Current should still be null.
        composite.Current.Should().BeNull();
    }

    [Fact]
    public void AsyncSelection_Changes_Current_After_Scheduler_Advance()
    {
        var (composite, hub, dispatcher) = BuildComposite(asyncSelection: true);
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Construct();

        composite.SelectComponent(child);
        dispatcher.AdvanceAll();

        composite.Current.Should().BeSameAs(child);
    }

    // ── Indexer ──────────────────────────────────────────────────────────────

    [Fact]
    public void Indexer_Returns_Correct_Child()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        composite.Add(c1);
        composite.Add(c2);

        composite[0].Should().BeSameAs(c1);
        composite[1].Should().BeSameAs(c2);
    }

    [Fact]
    public void Indexer_Setter_Replacing_Current_Clears_Current()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var oldChild = BuildChild(hub, dispatcher, "old");
        var newChild = BuildChild(hub, dispatcher, "new");
        composite.Add(oldChild);
        oldChild.Construct();
        composite.Current = oldChild;

        composite[0] = newChild;

        composite.Current.Should().BeNull(
            "current must be cleared when the slot holding it is replaced");
        composite[0].Should().BeSameAs(newChild);
        oldChild.Parent.Should().BeNull();
        newChild.Parent.Should().BeSameAs(composite);
    }

    [Fact]
    public void Indexer_Setter_Replacing_Non_Current_Leaves_Current_Intact()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var other = BuildChild(hub, dispatcher, "other");
        var sticky = BuildChild(hub, dispatcher, "sticky");
        var replacement = BuildChild(hub, dispatcher, "replacement");
        composite.Add(other);
        composite.Add(sticky);
        sticky.Construct();
        composite.Current = sticky;

        composite[0] = replacement;  // replace `other`, not `sticky`

        composite.Current.Should().BeSameAs(sticky,
            "current must survive when a different slot is replaced");
    }

    // ── Contains / IndexOf ────────────────────────────────────────────────────

    [Fact]
    public void Contains_Returns_True_For_Added_Child()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var child = BuildChild(hub, dispatcher);
        composite.Add(child);
        composite.Contains(child).Should().BeTrue();
    }

    [Fact]
    public void IndexOf_Returns_Correct_Index()
    {
        var (composite, hub, dispatcher) = BuildComposite();
        var c1 = BuildChild(hub, dispatcher, "c1");
        var c2 = BuildChild(hub, dispatcher, "c2");
        composite.Add(c1);
        composite.Add(c2);
        composite.IndexOf(c2).Should().Be(1);
    }

    // ── Builder validation ───────────────────────────────────────────────────

    [Fact]
    public void Builder_Throws_When_Name_Missing()
    {
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var act = () => CompositeVM<ComponentVM<string>>.Builder()
            .Services(hub, dispatcher).Build();
        act.Should().Throw<VMx.Builders.BuilderValidationException>();
    }

    [Fact]
    public void Builder_Throws_When_Services_Missing()
    {
        var act = () => CompositeVM<ComponentVM<string>>.Builder()
            .Name("x").Build();
        act.Should().Throw<VMx.Builders.BuilderValidationException>();
    }

    [Fact]
    public void Builder_Throws_When_Children_Missing()
    {
        // Per spec/10-builders.md §3 + ADR-0035: non-modeled CompositeVM<VM>
        // requires a Children(() => ...) factory. For an empty composite,
        // pass Children(() => Array.Empty<VM>()) explicitly.
        var hub = new TestHub();
        var dispatcher = new TestDispatcher();
        var act = () => CompositeVM<ComponentVM<string>>.Builder()
            .Name("x")
            .Services(hub, dispatcher)
            .Build();
        act.Should().Throw<VMx.Builders.BuilderValidationException>()
            .WithMessage("*Children*");
    }
}
