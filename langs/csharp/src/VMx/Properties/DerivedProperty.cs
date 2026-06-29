using System.Diagnostics.CodeAnalysis;
using System.Reactive.Linq;
using System.Reactive.Subjects;

namespace VMx.Properties;

/// <summary>
/// A read-only-or-read-write value computed from one or more source observables
/// via a pure transform. See spec/15-derived-properties.md and ADR-0011.
/// </summary>
public sealed class DerivedProperty<TValue> : IDisposable
{
    private readonly Subject<TValue> _changes = new();
    private readonly IDisposable _subscription;
    private readonly Func<TValue, bool>? _canSet;
    private readonly Action<TValue>? _setAction;

    // No initial value until a source emits. [MaybeNull] is the honest annotation
    // for an unconstrained generic field that is legitimately default/null before
    // first emission — reads are gated by _hasValue (see the Value getter), so the
    // single `!` there is a guarded assertion, not a blanket `default!` suppression.
    [MaybeNull]
    private TValue _value;
    private bool _hasValue;
    private bool _disposed;

    internal DerivedProperty(
        IObservable<TValue> derivedStream,
        Func<TValue, bool>? canSet,
        Action<TValue>? setAction)
    {
        _canSet = canSet;
        _setAction = setAction;
        _subscription = derivedStream.Subscribe(OnNext);
    }

    private void OnNext(TValue v)
    {
        if (!_hasValue)
        {
            _value = v;
            _hasValue = true;
            return;
        }
        // _value is non-null here: _hasValue is true so OnNext has stored a prior emission.
        if (EqualityComparer<TValue>.Default.Equals(v, _value!)) return;
        _value = v;
        _changes.OnNext(v);
    }

    /// <summary>Current value. Requires at least one source emission to have occurred.</summary>
    public TValue Value
    {
        get
        {
            if (!_hasValue)
                throw new InvalidOperationException("Derived property has no value yet — no source has emitted.");
            return _value!;
        }
    }

    /// <summary>Emits on every distinct recompute. Does not replay the initial value.</summary>
    public IObservable<TValue> ValueChanged => _changes.AsObservable();

    /// <summary>Returns true when <see cref="SetValue"/> may be called with <paramref name="value"/>.</summary>
    public bool CanSet(TValue value) => _canSet is not null && _canSet(value);

    /// <summary>Invokes the write-back action with <paramref name="value"/>.
    /// Raises if <see cref="CanSet"/> returns false.</summary>
    public void SetValue(TValue value)
    {
        if (!CanSet(value))
            throw new InvalidOperationException("CanSet returned false for the given value.");
        _setAction?.Invoke(value);
    }

    /// <summary>Tears down source subscriptions and completes <see cref="ValueChanged"/>.</summary>
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _subscription.Dispose();
        _changes.OnCompleted();
        _changes.Dispose();
    }
}

/// <summary>Factories for <see cref="DerivedProperty{TValue}"/>. See ADR-0011.</summary>
public static class DerivedProperty
{
    /// <summary>Build from a single source.</summary>
    public static DerivedProperty<TValue> From<T1, TValue>(
        IObservable<T1> s1,
        Func<T1, TValue> transform,
        Func<TValue, bool>? canSet = null,
        Action<TValue>? setAction = null)
    {
        return new DerivedProperty<TValue>(s1.Select(transform), canSet, setAction);
    }

    /// <summary>Build from two sources.</summary>
    public static DerivedProperty<TValue> From<T1, T2, TValue>(
        IObservable<T1> s1, IObservable<T2> s2,
        Func<T1, T2, TValue> transform,
        Func<TValue, bool>? canSet = null,
        Action<TValue>? setAction = null)
    {
        return new DerivedProperty<TValue>(s1.CombineLatest(s2, transform), canSet, setAction);
    }

    /// <summary>Build from three sources.</summary>
    public static DerivedProperty<TValue> From<T1, T2, T3, TValue>(
        IObservable<T1> s1, IObservable<T2> s2, IObservable<T3> s3,
        Func<T1, T2, T3, TValue> transform,
        Func<TValue, bool>? canSet = null,
        Action<TValue>? setAction = null)
    {
        return new DerivedProperty<TValue>(s1.CombineLatest(s2, s3, transform), canSet, setAction);
    }

    /// <summary>Build from four sources.</summary>
    public static DerivedProperty<TValue> From<T1, T2, T3, T4, TValue>(
        IObservable<T1> s1, IObservable<T2> s2, IObservable<T3> s3, IObservable<T4> s4,
        Func<T1, T2, T3, T4, TValue> transform,
        Func<TValue, bool>? canSet = null,
        Action<TValue>? setAction = null)
    {
        return new DerivedProperty<TValue>(s1.CombineLatest(s2, s3, s4, transform), canSet, setAction);
    }

    /// <summary>Build from five sources.</summary>
    public static DerivedProperty<TValue> From<T1, T2, T3, T4, T5, TValue>(
        IObservable<T1> s1, IObservable<T2> s2, IObservable<T3> s3, IObservable<T4> s4, IObservable<T5> s5,
        Func<T1, T2, T3, T4, T5, TValue> transform,
        Func<TValue, bool>? canSet = null,
        Action<TValue>? setAction = null)
    {
        return new DerivedProperty<TValue>(s1.CombineLatest(s2, s3, s4, s5, transform), canSet, setAction);
    }

    /// <summary>Build from N sources (N may exceed 5; the per-source type is erased).</summary>
    public static DerivedProperty<TValue> FromMany<TValue>(
        IReadOnlyList<IObservable<object?>> sources,
        Func<IReadOnlyList<object?>, TValue> transform,
        Func<TValue, bool>? canSet = null,
        Action<TValue>? setAction = null)
    {
        if (sources.Count == 0)
            throw new ArgumentException("At least one source is required.", nameof(sources));
        var stream = Observable.CombineLatest<object?>(sources)
            .Select(values => transform((IReadOnlyList<object?>)values));
        return new DerivedProperty<TValue>(stream, canSet, setAction);
    }
}
