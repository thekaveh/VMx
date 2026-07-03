using VMx.Messages;

namespace VMx.Forms;

/// <summary>
/// Published on the message hub when a <see cref="FormVM{TM}"/> reverts its
/// <c>Model</c> to <c>Snapshot</c> via <c>DenyCommand</c>.
///
/// See spec/20-form-vm.md §8 — Hub messages.
/// </summary>
/// <param name="Sender">The <see cref="FormVM{TM}"/> that was reverted.</param>
/// <param name="SenderName">Human-readable type name of the sender.</param>
public sealed record FormRevertedMessage(object Sender, string SenderName) : IMessage
{
    /// <inheritdoc/>
    public object SenderObject => Sender;
}
