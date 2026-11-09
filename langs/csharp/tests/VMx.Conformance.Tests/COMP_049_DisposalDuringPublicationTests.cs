using System.Collections.Specialized;
using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Lifecycle;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Conformance.Tests;

/// <summary>
/// COMP-049: a disposal requested during a change suppresses its hub message,
/// also when the disposal is deferred (spec/01-concepts.md §1.4,
/// spec/06-composite-vm.md §4/§4.2/§4.3, spec/07-group-vm.md §1, ADR-0190).
/// </summary>
public class COMP_049_DisposalDuringPublicationTests
{
    private static readonly TestDispatcher Dispatcher = new();

    private static ComponentVM<string> Child(MessageHub hub, string name)
        => ComponentVM<string>.Builder().Name(name).Services(hub, Dispatcher).Model(name).Build();

    private static CompositeVM<IComponentVM> Composite(
        MessageHub hub, string name, Action<IComponentVM?>? onCurrentChanged = null)
    {
        var builder = CompositeVM<IComponentVM>.Builder()
            .Name(name).Services(hub, Dispatcher).Children(() => []);
        if (onCurrentChanged is not null) builder = builder.OnCurrentChanged(onCurrentChanged);
        return builder.Build();
    }

    private static GroupVM<IComponentVM> Group(MessageHub hub, string name)
        => GroupVM<IComponentVM>.Builder()
            .Name(name).Services(hub, Dispatcher).Children(() => []).Build();

    private static List<string> HubLog(MessageHub hub)
    {
        var log = new List<string>();
        hub.Messages.OfType<CollectionChangedMessage<IComponentVM>>()
            .Subscribe(message => log.Add($"{((IComponentVM)message.Sender).Name}:{message.Action}"));
        return log;
    }

    [Fact, Trait("Conformance", "COMP-049")]
    public void COMP_049_Transfer_From_A_Self_Disposing_Old_Parent_Publishes_Only_The_New_Add()
    {
        using var hub = new MessageHub();
        CompositeVM<IComponentVM>? old = null;
        old = Composite(hub, "old", current =>
        {
            if (current is null) old!.Dispose();
        });
        var target = Composite(hub, "new");
        var x = Child(hub, "x");
        old.Add(x);
        old.Current = x;
        var local = new List<NotifyCollectionChangedAction>();
        old.CollectionChanged += (_, e) => local.Add(e.Action);
        var log = HubLog(hub);

        target.Add(x);

        log.Should().Equal("new:Add");
        old.Status.Should().Be(ConstructionStatus.Disposed);
        local.Should().Equal(NotifyCollectionChangedAction.Remove);
        target.Should().ContainSingle(item => ReferenceEquals(item, x));
    }

    [Fact, Trait("Conformance", "COMP-049")]
    public void COMP_049_Composite_Add_Whose_Local_Subscriber_Disposes_Publishes_Nothing()
    {
        using var hub = new MessageHub();
        var p = Composite(hub, "p");
        var local = new List<NotifyCollectionChangedAction>();
        p.CollectionChanged += (_, e) =>
        {
            local.Add(e.Action);
            p.Dispose();
        };
        var log = HubLog(hub);

        p.Add(Child(hub, "c"));

        local.Should().Equal(NotifyCollectionChangedAction.Add);
        log.Should().BeEmpty();
        p.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact, Trait("Conformance", "COMP-049")]
    public void COMP_049_Composite_Move_Whose_Local_Subscriber_Disposes_Publishes_Nothing()
    {
        using var hub = new MessageHub();
        var p = Composite(hub, "p");
        p.Add(Child(hub, "a"));
        p.Add(Child(hub, "b"));
        var local = new List<NotifyCollectionChangedAction>();
        p.CollectionChanged += (_, e) =>
        {
            local.Add(e.Action);
            p.Dispose();
        };
        var log = HubLog(hub);

        p.Move(0, 1);

        local.Should().Equal(NotifyCollectionChangedAction.Move);
        log.Should().BeEmpty();
        p.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact, Trait("Conformance", "COMP-049")]
    public void COMP_049_Group_Add_Whose_Local_Subscriber_Disposes_Publishes_Nothing()
    {
        using var hub = new MessageHub();
        var p = Group(hub, "p");
        var local = new List<NotifyCollectionChangedAction>();
        p.CollectionChanged += (_, e) =>
        {
            local.Add(e.Action);
            p.Dispose();
        };
        var log = HubLog(hub);

        p.Add(Child(hub, "c"));

        local.Should().Equal(NotifyCollectionChangedAction.Add);
        log.Should().BeEmpty();
        p.Status.Should().Be(ConstructionStatus.Disposed);
    }

    [Fact, Trait("Conformance", "COMP-049")]
    public void COMP_049_Group_Move_Whose_Local_Subscriber_Disposes_Publishes_Nothing()
    {
        using var hub = new MessageHub();
        var p = Group(hub, "p");
        p.Add(Child(hub, "a"));
        p.Add(Child(hub, "b"));
        var local = new List<NotifyCollectionChangedAction>();
        p.CollectionChanged += (_, e) =>
        {
            local.Add(e.Action);
            p.Dispose();
        };
        var log = HubLog(hub);

        p.Move(0, 1);

        local.Should().Equal(NotifyCollectionChangedAction.Move);
        log.Should().BeEmpty();
        p.Status.Should().Be(ConstructionStatus.Disposed);
    }
}
