using System.Runtime.ExceptionServices;

namespace VMx.Internal;

/// <summary>
/// Wraps a library stream so that a failing subscriber neither stops the
/// delivery to the other subscribers nor detaches itself or the library's own
/// source subscription (spec/03 §3.6, ADR-0191).
/// </summary>
/// <remarks>
/// Each subscriber is wrapped in an observer whose <c>OnNext</c> discards a
/// failure, as the hub does (<c>HUB-007</c>). The wrapper is the observer that
/// an Rx operator in <paramref name="source"/> sees, so the Rx safeguard never
/// sees a throw and never disposes the subscription. When
/// <paramref name="captureCompletionFailures"/> is set, a failing completion
/// observer does not stop the later ones either: the owner reads the first
/// failure with <see cref="TakeCompletionFailure"/> and rethrows it.
/// </remarks>
internal sealed class IsolatedObservable<T>(IObservable<T> source, bool captureCompletionFailures = false) : IObservable<T>
{
    private readonly bool _captureCompletionFailures = captureCompletionFailures;
    private ExceptionDispatchInfo? _completionFailure;

    public IDisposable Subscribe(IObserver<T> observer)
    {
        ThrowHelper.ThrowIfNull(observer, nameof(observer));
        return source.Subscribe(new IsolatingObserver(this, observer));
    }

    /// <summary>Returns and clears the first failure of a completion observer.</summary>
    public ExceptionDispatchInfo? TakeCompletionFailure() => Interlocked.Exchange(ref _completionFailure, null);

    private sealed class IsolatingObserver(IsolatedObservable<T> owner, IObserver<T> inner) : IObserver<T>
    {
        public void OnNext(T value)
        {
            try { inner.OnNext(value); }
            catch { /* stream-fed route: discard the failure and keep the subscriber attached (spec/03 §3.6) */ }
        }

        public void OnError(Exception error) => inner.OnError(error);

        public void OnCompleted()
        {
            if (!owner._captureCompletionFailures)
            {
                inner.OnCompleted();
                return;
            }

            try { inner.OnCompleted(); }
            catch (Exception error)
            {
                Interlocked.CompareExchange(ref owner._completionFailure, ExceptionDispatchInfo.Capture(error), null);
            }
        }
    }
}
