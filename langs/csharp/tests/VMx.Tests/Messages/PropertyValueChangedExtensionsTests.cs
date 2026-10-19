using FluentAssertions;
using VMx.Components;
using VMx.Messages;
using VMx.Services;
using VMx.Tests.Helpers;
using Xunit;

namespace VMx.Tests.Messages;

public class PropertyValueChangedExtensionsTests
{
    private sealed class TestSource
    {
        private int _count;
        private string _label = string.Empty;

        public int Count
        {
            get => _count;
            set
            {
                var prev = _count;
                _count = value;
                if (prev != value)
                    Hub?.Send(PropertyChangedMessage<TestSource>.Create(this, "test-source", nameof(Count)));
            }
        }

        public string Label
        {
            get => _label;
            set
            {
                var prev = _label;
                _label = value;
                if (prev != value)
                    Hub?.Send(PropertyChangedMessage<TestSource>.Create(this, "test-source", nameof(Label)));
            }
        }

        public MessageHub? Hub { get; set; }
    }

    [Fact]
    public void PropertyValueChangedMessagesFor_Returns_Observable_Of_Property_Values()
    {
        using var hub = new MessageHub();
        var source = new TestSource { Hub = hub };
        var values = new List<int>();

        using var sub = hub.PropertyValueChangedMessagesFor(source, s => s.Count)
                           .Subscribe(values.Add);

        source.Count = 1;
        source.Count = 2;
        source.Count = 3;

        values.Should().Equal(1, 2, 3);
    }

    [Fact]
    public void PropertyValueChangedMessagesFor_Filters_By_Sender()
    {
        using var hub = new MessageHub();
        var source1 = new TestSource { Hub = hub };
        var source2 = new TestSource { Hub = hub };
        var values1 = new List<int>();
        var values2 = new List<int>();

        using var sub1 = hub.PropertyValueChangedMessagesFor(source1, s => s.Count).Subscribe(values1.Add);
        using var sub2 = hub.PropertyValueChangedMessagesFor(source2, s => s.Count).Subscribe(values2.Add);

        source1.Count = 10;
        source2.Count = 20;

        values1.Should().Equal(10);
        values2.Should().Equal(20);
    }

    [Fact]
    public void PropertyValueChangedMessagesFor_Filters_By_PropertyName()
    {
        using var hub = new MessageHub();
        var source = new TestSource { Hub = hub };
        var counts = new List<int>();
        var labels = new List<string>();

        using var subCount = hub.PropertyValueChangedMessagesFor(source, s => s.Count).Subscribe(counts.Add);
        using var subLabel = hub.PropertyValueChangedMessagesFor(source, s => s.Label).Subscribe(labels.Add);

        source.Count = 42;
        source.Label = "hello";

        counts.Should().Equal(42);
        labels.Should().Equal("hello");
    }

    [Fact]
    public void PropertyValueChangedMessagesFor_Snapshot_Value_At_Message_Time()
    {
        using var hub = new MessageHub();
        var source = new TestSource { Hub = hub };
        var snapshots = new List<int>();

        using var sub = hub.PropertyValueChangedMessagesFor(source, s => s.Count).Subscribe(snapshots.Add);

        source.Count = 5;
        source.Count = 10;

        snapshots.Should().Equal(5, 10);
    }
    [Fact]
    public void PropertyValueChangedMessagesFor_Observes_Real_ComponentVM_Property_Changes()
    {
        // Real VMs publish PropertyChangedMessage<IComponentVM>, not
        // PropertyChangedMessage<ComponentVM<M>>; matching is by reference-equal
        // sender (spec/03 §7.1 step 1), not by the inferred TSource.
        using var hub = new MessageHub();
        var vm = ComponentVM<string>.Builder()
            .Name("v1")
            .Services(hub, new TestDispatcher())
            .Model("0")
            .Build();
        var other = ComponentVM<string>.Builder()
            .Name("v2")
            .Services(hub, new TestDispatcher())
            .Model("0")
            .Build();
        var values = new List<string?>();

        using var sub = hub.PropertyValueChangedMessagesFor(vm, x => x.Model).Subscribe(values.Add);

        vm.Model = "1";
        other.Model = "x";
        vm.Model = "2";

        values.Should().Equal("1", "2");
    }
}
