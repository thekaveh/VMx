"""CommandBridge — VMx :class:`RelayCommand` → Textual :class:`Button`.

See scenario §7.1 (CommandBridge) and plan §4.b.

Two responsibilities:

1. Mirror ``command.can_execute()`` onto ``button.disabled`` (inverted), both
   eagerly (at bind time) and reactively (each ``can_execute_changed`` tick).
2. Route button presses to ``command.execute()``.

For (2) we monkey-patch ``button.press`` — the single funnel both activation
paths share in Textual 8.x: a mouse click runs ``_on_click → press()`` and the
Enter key binding runs ``action_press → press()``. (An earlier revision
patched ``action_press``, which the click path never calls — every mouse
click on a bound button was silently dropped.)
Wiring on ``Button.Pressed`` would require a host ``App`` / ``Widget`` to
install a message handler, which the adapter has no business doing; the
``press`` override keeps the bridge UI-thread agnostic and unit-testable in
pure pytest.

The disposable returned cancels the ``can_execute_changed`` subscription. The
``press`` override is left in place — the button is logically owned by the
bridge for its lifetime.
"""

from __future__ import annotations

from typing import Any

from reactivex.abc import DisposableBase

from vmx.commands.protocols import Command


def bind_command(button: Any, command: Command) -> DisposableBase:
    """Bind ``button`` to ``command``.

    Initialises ``button.disabled = not command.can_execute()``, redirects
    ``button.press`` (the shared click + Enter funnel) to
    ``command.execute()``, and subscribes to ``command.can_execute_changed``
    to keep ``button.disabled`` in sync.

    Returns a :class:`~reactivex.abc.DisposableBase` for the
    ``can_execute_changed`` subscription. Accepts any :class:`Command`
    (including decorated ones such as ``ConfirmationDecoratorCommand``) —
    shared delete-command behavior.
    """
    button.disabled = not command.can_execute()

    def _press() -> None:
        # Mirror Button.press()'s own disabled guard.
        if not button.disabled:
            command.execute()

    button.press = _press

    def _on_can_execute_changed(_value: object) -> None:
        button.disabled = not command.can_execute()

    subscription = command.can_execute_changed.subscribe(
        on_next=_on_can_execute_changed
    )
    return subscription
