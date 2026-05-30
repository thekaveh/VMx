"""CommandBridge — VMx :class:`RelayCommand` → Textual :class:`Button`.

See scenario §7.1 (CommandBridge) and plan §4.b.

Two responsibilities:

1. Mirror ``command.can_execute()`` onto ``button.disabled`` (inverted), both
   eagerly (at bind time) and reactively (each ``can_execute_changed`` tick).
2. Route button presses to ``command.execute()``.

For (2) we monkey-patch ``button.action_press`` — Textual invokes that method
whenever the user activates the button (key binding or click). Wiring on
``Button.Pressed`` would require a host ``App`` / ``Widget`` to install a
message handler, which the adapter has no business doing; ``action_press``
keeps the bridge UI-thread agnostic and unit-testable in pure pytest.

The disposable returned cancels the ``can_execute_changed`` subscription. The
``action_press`` override is left in place — the button is logically owned by
the bridge for its lifetime.
"""

from __future__ import annotations

from typing import Any

from reactivex.abc import DisposableBase

from vmx.commands.protocols import Command


def bind_command(button: Any, command: Command) -> DisposableBase:
    """Bind ``button`` to ``command``.

    Initialises ``button.disabled = not command.can_execute()``, redirects
    ``button.action_press`` to ``command.execute()``, and subscribes to
    ``command.can_execute_changed`` to keep ``button.disabled`` in sync.

    Returns a :class:`~reactivex.abc.DisposableBase` for the
    ``can_execute_changed`` subscription. Accepts any :class:`Command`
    (including decorated ones such as ``ConfirmationDecoratorCommand``) —
    round-3 Critical-1.
    """
    button.disabled = not command.can_execute()

    def _press() -> None:
        command.execute()

    button.action_press = _press

    def _on_can_execute_changed(_value: object) -> None:
        button.disabled = not command.can_execute()

    subscription = command.can_execute_changed.subscribe(on_next=_on_can_execute_changed)
    return subscription
