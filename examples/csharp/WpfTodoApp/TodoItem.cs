namespace WpfTodoApp;

/// <summary>
/// Plain domain model for a single to-do item.
/// Immutable; the VM wraps it with mutable Done state via the Model setter.
/// </summary>
public sealed record TodoItem(string Title, bool Done = false);
