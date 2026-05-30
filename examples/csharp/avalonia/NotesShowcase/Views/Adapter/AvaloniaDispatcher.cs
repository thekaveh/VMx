using System.Reactive.Concurrency;
using System.Reactive.Disposables;
using Avalonia.Threading;
using VMx.Services;

namespace NotesShowcase.Views.Adapter;

/// <summary>
/// Dispatcher (scenario §7.1, plan §4.a): implements <see cref="IDispatcher"/>
/// (spec ch. 11) against Avalonia's UI loop.
///
/// <list type="bullet">
/// <item><description><see cref="Foreground"/> posts work via <see cref="Dispatcher.UIThread"/> through an <see cref="AvaloniaUiScheduler"/> wrapper.</description></item>
/// <item><description><see cref="Background"/> uses <see cref="TaskPoolScheduler.Default"/>, matching the spec's default.</description></item>
/// </list>
///
/// <para>
/// VMx C# does not declare a separate <c>IRxDispatcher</c>; the contract is
/// <see cref="IDispatcher"/> (foreground + background <see cref="IScheduler"/>).
/// The Phase 4.a plan's "IRxDispatcher" sketch refers to the Python/TS naming;
/// in C# the interface is <see cref="IDispatcher"/>.
/// </para>
/// </summary>
public sealed class AvaloniaDispatcher : VMx.Services.IDispatcher
{
    /// <inheritdoc/>
    public IScheduler Foreground { get; }

    /// <inheritdoc/>
    public IScheduler Background { get; }

    /// <summary>
    /// Builds a dispatcher whose <see cref="Foreground"/> targets Avalonia's
    /// <see cref="Dispatcher.UIThread"/> and whose <see cref="Background"/> uses
    /// <see cref="TaskPoolScheduler.Default"/>.
    /// </summary>
    public AvaloniaDispatcher()
    {
        Foreground = new AvaloniaUiScheduler();
        Background = TaskPoolScheduler.Default;
    }

    /// <summary>
    /// Test/diagnostic constructor: allows substituting explicit schedulers
    /// (parity with <see cref="RxDispatcher"/>'s deterministic constructor).
    /// </summary>
    internal AvaloniaDispatcher(IScheduler foreground, IScheduler background)
    {
        Foreground = foreground;
        Background = background;
    }

    /// <summary>
    /// Minimal <see cref="IScheduler"/> that marshals every action onto
    /// <see cref="Dispatcher.UIThread"/>.
    /// </summary>
    private sealed class AvaloniaUiScheduler : IScheduler
    {
        public DateTimeOffset Now => DateTimeOffset.Now;

        public IDisposable Schedule<TState>(TState state, Func<IScheduler, TState, IDisposable> action)
        {
            var cancel = new SingleAssignmentDisposable();
            Dispatcher.UIThread.Post(() =>
            {
                if (cancel.IsDisposed) return;
                cancel.Disposable = action(this, state);
            });
            return cancel;
        }

        public IDisposable Schedule<TState>(TState state, TimeSpan dueTime, Func<IScheduler, TState, IDisposable> action)
        {
            if (dueTime <= TimeSpan.Zero)
                return Schedule(state, action);

            var cancel = new SingleAssignmentDisposable();
            var timer = new DispatcherTimer { Interval = dueTime };
            timer.Tick += OnTick;
            timer.Start();
            return new CompositeDisposable(cancel, new ActionDisposable(() =>
            {
                timer.Tick -= OnTick;
                timer.Stop();
            }));

            void OnTick(object? sender, EventArgs e)
            {
                timer.Tick -= OnTick;
                timer.Stop();
                if (cancel.IsDisposed) return;
                cancel.Disposable = action(this, state);
            }
        }

        public IDisposable Schedule<TState>(TState state, DateTimeOffset dueTime, Func<IScheduler, TState, IDisposable> action)
            => Schedule(state, dueTime - Now, action);

        private sealed class ActionDisposable : IDisposable
        {
            private Action? _action;
            public ActionDisposable(Action action) => _action = action;
            public void Dispose()
            {
                var a = Interlocked.Exchange(ref _action, null);
                a?.Invoke();
            }
        }
    }
}
