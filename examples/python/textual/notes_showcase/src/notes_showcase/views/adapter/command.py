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

A command with an ``errors`` channel, such as ``AsyncRelayCommand``, reports a
fire-and-forget failure there instead of to the caller. The bridge logs each
failure and shows it as an error notification, as the NiceGUI binding does.
The ``Command`` protocol has no ``errors`` member, so the bridge detects the
channel at run time.

The disposable returned cancels the ``can_execute_changed`` and ``errors``
subscriptions. The ``press`` override is left in place — the button is
logically owned by the bridge for its lifetime.
"""

from __future__ import annotations

import logging
from typing import Any

import reactivex as rx
from reactivex.abc import DisposableBase
from reactivex.disposable import CompositeDisposable
from vmx.commands.protocols import Command, ParameterizedCommand

_log = logging.getLogger(__name__)


def bind_command(
    button: Any,
    command: Command | ParameterizedCommand[Any],
    parameter: Any = None,
) -> DisposableBase:
    """Bind ``button`` to ``command``.

    Initialises ``button.disabled = not command.can_execute()``, redirects
    ``button.press`` (the shared click + Enter funnel) to
    ``command.execute()``, and subscribes to ``command.can_execute_changed``
    to keep ``button.disabled`` in sync.

    When the command has an ``errors`` channel, each failure on it is logged
    and shown as an error notification that names the failure.

    Returns a :class:`~reactivex.abc.DisposableBase` for the
    ``can_execute_changed`` and ``errors`` subscriptions. Accepts any :class:`Command`
    (including decorated ones such as ``ConfirmationDecoratorCommand``) —
    shared delete-command behavior. ``parameter`` is passed to
    ``can_execute`` and ``execute`` (for parameterised commands such as
    ``RelayCommandOf``).
    """
    button.disabled = not command.can_execute(parameter)

    def _press() -> None:
        # Mirror Button.press()'s own disabled guard.
        if not button.disabled:
            command.execute(parameter)

    button.press = _press

    def _on_can_execute_changed(_value: object) -> None:
        button.disabled = not command.can_execute(parameter)

    def _report(error: BaseException) -> None:
        _log.error("command failed", exc_info=error)
        # A button that left the DOM has no app to notify.
        if button.is_attached:
            button.notify(f"Command failed: {error}", severity="error")

    disposables: list[DisposableBase] = [
        command.can_execute_changed.subscribe(on_next=_on_can_execute_changed)
    ]
    errors: rx.Observable[BaseException] | None = getattr(command, "errors", None)
    if errors is not None:
        disposables.append(errors.subscribe(on_next=_report))
    return CompositeDisposable(*disposables)
