using System.ComponentModel;
using VMx.Properties;

namespace NotesShowcase.Views.Adapter;

/// <summary>
/// PropertyBridge companion for a <see cref="DerivedProperty{T}"/>, providing
/// the same derived-property binding role as the other showcase adapters.
///
/// <para>
/// <see cref="DerivedProperty{T}"/> lives outside the hub message graph: it
/// owns its own <see cref="DerivedProperty{T}.ValueChanged"/> observable and
/// never publishes a <see cref="VMx.Messages.PropertyChangedMessage{TSender}"/>.
/// Avalonia's binding system therefore cannot observe recomputes through the
/// usual <see cref="INotifyPropertyChanged"/> path on the DP itself. This
/// adapter subscribes to <c>ValueChanged</c> and raises
/// <c>PropertyChanged("Value")</c> so XAML can bind <c>{Binding Foo.Value}</c>
/// against a wrapper that lives next to the original DP on the VM.
/// </para>
///
/// <para>
/// Semantics mirror the Python / TypeScript adapters:
/// <list type="bullet">
///   <item><see cref="Value"/> reads through to the wrapped DP and is safe to
///   call once the DP has received its first source emission (DPs in this
///   showcase are seeded by <c>BehaviorSubject</c> sources so the first
///   emission is synchronous at construct time).</item>
///   <item><see cref="PropertyChanged"/> fires once per distinct emission
///   (the wrapped DP equality-guards via <c>EqualityComparer&lt;T&gt;.Default</c>).</item>
///   <item><see cref="Dispose"/> cancels the subscription. Idempotent.</item>
/// </list>
/// </para>
/// </summary>
public sealed class BindableDerived<T> : INotifyPropertyChanged, IDisposable
{
    private readonly DerivedProperty<T> _source;
    private readonly IDisposable _subscription;
    private bool _disposed;

    /// <inheritdoc/>
    public event PropertyChangedEventHandler? PropertyChanged;

    /// <summary>
    /// Wraps <paramref name="source"/> with an INPC-aware <see cref="Value"/>
    /// accessor.
    /// </summary>
    /// <param name="source">The wrapped derived property. Required.</param>
    /// <exception cref="ArgumentNullException">If <paramref name="source"/> is null.</exception>
    public BindableDerived(DerivedProperty<T> source)
    {
        ArgumentNullException.ThrowIfNull(source);
        _source = source;
        _subscription = _source.ValueChanged.Subscribe(_ => RaiseValueChanged());
    }

    /// <summary>
    /// Current derived value. Reads through to <see cref="DerivedProperty{T}.Value"/>;
    /// returns <c>default!</c> if the wrapped DP has not received a source
    /// emission yet (mirrors the Python / React adapters' pre-emission fallback).
    /// </summary>
    public T Value
    {
        get
        {
            try { return _source.Value; }
            catch (InvalidOperationException) { return default!; }
        }
    }

    private void RaiseValueChanged()
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Value)));

    /// <summary>Cancels the subscription. Idempotent.</summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _subscription.Dispose();
    }
}
