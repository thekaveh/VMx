using System.Reactive.Linq;
using System.Reactive.Subjects;

namespace VMx.State;

/// <summary>
/// Owns one active discriminator key with modal precedence helpers.
/// </summary>
/// <typeparam name="TKey">Discriminator key type.</typeparam>
public sealed class DiscriminatorVM<TKey> : IDisposable
    where TKey : notnull
{
    private readonly Subject<TKey> _activeChanged = new();
    private readonly Stack<TKey> _modalStack = new();
    private bool _disposed;

    /// <summary>Creates a discriminator with the initial active key.</summary>
    public DiscriminatorVM(TKey initial)
    {
        ActiveKey = initial;
    }

    /// <summary>Currently active key.</summary>
    public TKey ActiveKey { get; private set; }

    /// <summary>Observable of active-key changes.</summary>
    public IObservable<TKey> ActiveChanged => _activeChanged.AsObservable();

    /// <summary>Returns <see langword="true"/> when <paramref name="key"/> is active.</summary>
    public bool IsActive(TKey key) => EqualityComparer<TKey>.Default.Equals(ActiveKey, key);

    /// <summary>Set the active key. Re-setting the same key is a no-op.</summary>
    public void SetActiveKey(TKey key)
    {
        if (_disposed || IsActive(key)) return;
        ActiveKey = key;
        _activeChanged.OnNext(key);
    }

    /// <summary>Activate <paramref name="modalKey"/> and remember the previous key.</summary>
    public void ModalOpen(TKey modalKey)
    {
        if (_disposed) return;
        _modalStack.Push(ActiveKey);
        SetActiveKey(modalKey);
    }

    /// <summary>Restore the active key that preceded the most recent modal.</summary>
    public void ModalClose()
    {
        if (_disposed || _modalStack.Count == 0) return;
        SetActiveKey(_modalStack.Pop());
    }

    /// <summary>Complete the active-changed stream. Idempotent.</summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _activeChanged.OnCompleted();
        _activeChanged.Dispose();
    }
}
