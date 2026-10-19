using FluentAssertions;
using VMx.Components;
using VMx.Composites;
using VMx.Lifecycle;
using VMx.Services;
using Xunit;

namespace VMx.Tests.Composites;

public class CustomChildPopulationTests
{
    // A custom IComponentVM whose synchronous Construct() leaves it pending.
    private sealed class PendingCustomVM : IComponentVM
    {
        public string Name => "custom";
        public string Hint => "";
        public ViewModelType Type => ViewModelType.Component;
        public bool IsCurrent => false;
        public bool IsConstructed => Status == ConstructionStatus.Constructed;
        public ConstructionStatus Status { get; private set; } = ConstructionStatus.Destructed;
        public IMessageHub Hub => NullMessageHub.Instance;
        public System.Windows.Input.ICommand SelectCommand => null!;
        public System.Windows.Input.ICommand DeselectCommand => null!;
        public System.Windows.Input.ICommand SelectNextCommand => null!;
        public System.Windows.Input.ICommand SelectPreviousCommand => null!;
        public System.Windows.Input.ICommand ReconstructCommand => null!;
        public bool CanConstruct() => Status == ConstructionStatus.Destructed;
        public void Construct() => Status = ConstructionStatus.Constructing;
        public Task ConstructAsync()
        {
            Status = ConstructionStatus.Constructed;
            return Task.CompletedTask;
        }
        public bool CanDestruct() => Status == ConstructionStatus.Constructed;
        public void Destruct() => Status = ConstructionStatus.Destructed;
        public Task DestructAsync()
        {
            Destruct();
            return Task.CompletedTask;
        }
        public bool CanReconstruct() => false;
        public void Reconstruct() { }
        public Task ReconstructAsync() => Task.CompletedTask;
        public bool CanSelect() => false;
        public void Select() { }
        public bool CanDeselect() => false;
        public void Deselect() { }
        public void Dispose() => Status = ConstructionStatus.Disposed;
        public event System.ComponentModel.PropertyChangedEventHandler? PropertyChanged
        {
            add { }
            remove { }
        }
    }

    [Fact]
    public async Task Construct_DrivesAPendingCustomFactoryChild()
    {
        var child = new PendingCustomVM();
        var composite = CompositeVM<IComponentVM>.Builder()
            .Name("root")
            .Services(NullMessageHub.Instance, NullDispatcher.Instance)
            .Children(() => [child])
            .Build();

        await composite.ConstructAsync();

        child.Status.Should().Be(ConstructionStatus.Constructed);
        composite.Status.Should().Be(ConstructionStatus.Constructed);
        composite.Dispose();
    }
}
