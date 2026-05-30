using System.ComponentModel;
using System.Reactive.Linq;
using VMx.Messages;
using VMx.Services;

namespace NotesShowcase.Views.Adapter;

/// <summary>
/// PropertyBridge (scenario §7.1, plan §4.a): subscribes once to a VM's
/// <see cref="IMessageHub"/>, filters <see cref="IPropertyChangedMessage{TSender}"/>
/// for messages whose sender is the wrapped VM, and re-raises them on
/// <see cref="INotifyPropertyChanged.PropertyChanged"/>.
///
/// <para>
/// Per scenario §7.2 ("Whole-VM subscription"), this is a single hub subscription
/// per VM. Avalonia's binding system can target the underlying VM as DataContext
/// directly — every example VM in <c>NotesShowcase.ViewModels</c> already
/// implements <see cref="INotifyPropertyChanged"/>. <see cref="BindableVm"/>
/// exists as a sidecar that adds the hub-message INPC plumbing for cases where
/// XAML needs change notifications driven by hub events (e.g., aggregate-level
/// property changes that aren't surfaced by individual leaf VMs' own INPC).
/// </para>
///
/// <para>
/// Disposing the bridge cancels the hub subscription. Construction is the only
/// observed side-effect (no message is published).
/// </para>
/// </summary>
public sealed class BindableVm : INotifyPropertyChanged, IDisposable
{
    private readonly IDisposable _subscription;
    private bool _disposed;

    /// <summary>The wrapped source VM; typically also used as the actual XAML DataContext.</summary>
    public object Source { get; }

    /// <inheritdoc/>
    public event PropertyChangedEventHandler? PropertyChanged;

    /// <summary>
    /// Creates a bridge that re-emits <paramref name="hub"/>'s
    /// <see cref="IPropertyChangedMessage{TSender}"/> events whose sender is
    /// <paramref name="vm"/> as <see cref="PropertyChanged"/>.
    /// </summary>
    /// <param name="vm">The VM whose property-change messages should be mirrored. Required.</param>
    /// <param name="hub">The hub the VM publishes to. Required.</param>
    /// <exception cref="ArgumentNullException">If <paramref name="vm"/> or <paramref name="hub"/> is null.</exception>
    public BindableVm(object vm, IMessageHub hub)
    {
        ArgumentNullException.ThrowIfNull(vm);
        ArgumentNullException.ThrowIfNull(hub);

        Source = vm;
        _subscription = hub.Messages
            .OfType<IMessage>()
            .Where(m => IsPropertyChangedFor(m, vm))
            .Subscribe(m => Raise(GetPropertyName(m)));
    }

    private static bool IsPropertyChangedFor(IMessage message, object vm)
    {
        // PropertyChangedMessage<T> is a generic record; we filter via the
        // open-generic interface so any T is accepted.
        if (message is not IMessage typed) return false;
        var t = message.GetType();
        if (!t.IsGenericType) return false;
        if (t.GetGenericTypeDefinition() != typeof(PropertyChangedMessage<>)) return false;
        return ReferenceEquals(message.SenderObject, vm);
    }

    private static string GetPropertyName(IMessage message)
    {
        // The runtime type is PropertyChangedMessage<TSender>; PropertyName is a
        // public record property. Reflection lookup is cheap and avoids
        // taking a dependency on a closed generic.
        var prop = message.GetType().GetProperty(nameof(IPropertyChangedMessage<object>.PropertyName));
        return (string?)prop?.GetValue(message) ?? string.Empty;
    }

    private void Raise(string propertyName)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));

    /// <summary>Cancels the hub subscription. Idempotent.</summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _subscription.Dispose();
    }
}
