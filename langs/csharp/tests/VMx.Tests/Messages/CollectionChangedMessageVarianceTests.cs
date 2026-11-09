using System.Reactive.Linq;
using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Groups;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Messages;

/// <summary>
/// <see cref="ICollectionChangedMessage{T}"/> is covariant in <c>T</c> (#1356).
/// One <c>ICollectionChangedMessage&lt;IComponentVM&gt;</c> hub filter receives the
/// changes of a container whose child type is a concrete view-model type.
/// </summary>
public class CollectionChangedMessageVarianceTests
{
    private static readonly TestDispatcher Dispatcher = new();

    private static ComponentVM<string> Child(MessageHub hub, string name)
        => ComponentVM<string>.Builder().Name(name).Services(hub, Dispatcher).Model(name).Build();

    public static IEnumerable<object[]> Containers()
    {
        yield return ["composite"];
        yield return ["group"];
    }

    private static IList<ComponentVM<string>> Container(string kind, MessageHub hub) => kind == "composite"
        ? CompositeVM<ComponentVM<string>>.Builder().Name("c").Services(hub, Dispatcher).Children(() => []).Build()
        : GroupVM<ComponentVM<string>>.Builder().Name("g").Services(hub, Dispatcher).Children(() => []).Build();

    [Theory]
    [MemberData(nameof(Containers))]
    public void Interface_Filter_On_IComponentVM_Receives_Concrete_Child_Type_Changes(string kind)
    {
        using var hub = new MessageHub();
        var container = Container(kind, hub);
        var viaInterface = new List<ICollectionChangedMessage<IComponentVM>>();
        var viaConcrete = new List<CollectionChangedMessage<ComponentVM<string>>>();
        using var interfaceSub = hub.Messages.OfType<ICollectionChangedMessage<IComponentVM>>()
            .Where(message => ReferenceEquals(message.SenderObject, container))
            .Subscribe(viaInterface.Add);
        using var concreteSub = hub.Messages.OfType<CollectionChangedMessage<ComponentVM<string>>>()
            .Where(message => ReferenceEquals(message.Sender, container))
            .Subscribe(viaConcrete.Add);

        var child = Child(hub, "a");
        container.Add(child);

        viaInterface.Should().ContainSingle();
        viaInterface[0].NewItems.Should().ContainSingle().Which.Should().BeSameAs(child);
        viaConcrete.Should().ContainSingle();
        viaConcrete[0].Should().BeSameAs(viaInterface[0]);
    }
}
