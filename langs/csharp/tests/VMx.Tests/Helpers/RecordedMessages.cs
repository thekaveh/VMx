using System.Reactive.Linq;
using VMx.Messages;

namespace VMx.Tests.Helpers;

/// <summary>
/// Subscribes to an IObservable&lt;IMessage&gt; and records everything
/// observed. Test code asserts against <see cref="Items"/>.
/// </summary>
public sealed class RecordedMessages<TMessage> : IDisposable where TMessage : IMessage
{
    private readonly IDisposable _subscription;

    public List<TMessage> Items { get; } = new();

    public RecordedMessages(IObservable<IMessage> source)
    {
        _subscription = source.OfType<TMessage>().Subscribe(Items.Add);
    }

    public void Dispose() => _subscription.Dispose();
}
