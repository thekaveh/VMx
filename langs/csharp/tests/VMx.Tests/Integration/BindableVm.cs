using System.ComponentModel;
using System.Reactive.Concurrency;
using System.Reactive.Linq;
using VMx.Components;
using VMx.Lifecycle;

namespace VMx.Tests.Integration;

/// <summary>
/// Binds a borrowed <see cref="ComponentVM{M}"/> to XAML. The VM's creator
/// constructs and disposes it; this adapter only observes it.
/// </summary>
public sealed class BindableVm<M> : INotifyPropertyChanged, IDisposable
{
    private readonly ComponentVM<M> _vm;
    private readonly IDisposable _subscription;

    /// <param name="vm">The VM to show.</param>
    /// <param name="host">
    /// The UI thread's scheduler, for example a
    /// <see cref="SynchronizationContextScheduler"/> created on the UI thread.
    /// </param>
    public BindableVm(ComponentVM<M> vm, IScheduler host)
    {
        _vm = vm;
        // ComponentVM<M> implements INotifyPropertyChanged: it raises Model on
        // assignment and Status on every lifecycle transition, on the thread
        // that made the change. Forward each notification on the UI thread.
        // Hub messages are not forwarded: the hub carries no Status change,
        // and its Model message would notify a second time.
        _subscription = Observable
            .FromEventPattern<PropertyChangedEventHandler, PropertyChangedEventArgs>(
                handler => vm.PropertyChanged += handler,
                handler => vm.PropertyChanged -= handler)
            .ObserveOn(host)
            .Subscribe(change => PropertyChanged?.Invoke(this, change.EventArgs));
    }

    /// <summary>The VM's model; assigning it replaces the VM's model.</summary>
    public M Model
    {
        get => _vm.Model;
        set => _vm.Model = value;
    }

    /// <summary>The VM's name.</summary>
    public string Name => _vm.Name;

    /// <summary>The VM's lifecycle status.</summary>
    public ConstructionStatus Status => _vm.Status;

    /// <inheritdoc/>
    public event PropertyChangedEventHandler? PropertyChanged;

    /// <summary>Stops observing the VM without changing its lifecycle.</summary>
    public void Dispose() => _subscription.Dispose();
}
