using System.Reactive.Subjects;
using VMx.Messages;
using VMx.Services;

namespace VMx.Tests.Helpers;

/// <summary>
/// In-process IMessageHub for tests. Backed by a Subject so subscribers
/// can use Rx operators (Where, ObserveOn, etc.) directly.
/// </summary>
public sealed class TestHub : IMessageHub, IDisposable
{
    private readonly Subject<IMessage> _subject = new();

    public IObservable<IMessage> Messages => _subject;

    public void Send<TMessage>(TMessage message) where TMessage : IMessage
        => _subject.OnNext(message);

    public void Dispose() => _subject.Dispose();
}
