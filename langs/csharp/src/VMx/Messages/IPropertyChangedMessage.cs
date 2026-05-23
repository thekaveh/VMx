namespace VMx.Messages;

/// <summary>
/// Emitted by a VM when a property's setter accepts a value different from the
/// existing one. See spec/03-messages.md §PropertyChangedMessage.
/// </summary>
/// <typeparam name="TSender">Compile-time type of the sender.</typeparam>
public interface IPropertyChangedMessage<out TSender> : IMessage<TSender>
{
    /// <summary>Name of the property whose value changed.</summary>
    string PropertyName { get; }
}
