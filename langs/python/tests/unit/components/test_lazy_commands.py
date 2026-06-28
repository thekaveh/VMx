"""VMX-018 regression — built-in commands are built lazily, not eagerly.

``_ComponentVMBase`` used to eagerly construct all five built-in RelayCommands
(plus five status-trigger subscriptions) in ``__init__``; four of them are
permanently inert on a leaf VM.  They are now built on first property access and
cached.  These tests assert the laziness (the private slot is ``None`` until the
property is read), the stable-instance caching, and that the preserved
status-trigger wiring still fires ``can_execute_changed`` on lifecycle
transitions (VMX-104 parity).
"""

from __future__ import annotations

from vmx.components.builders import ComponentVMBuilder
from vmx.services.dispatcher import RxDispatcher
from vmx.services.message_hub import MessageHub


def _leaf() -> object:
    return (
        ComponentVMBuilder().name("leaf").services(MessageHub(), RxDispatcher.immediate()).build()
    )


def test_commands_not_built_until_accessed() -> None:
    vm = _leaf()
    # No built-in command is constructed eagerly.
    assert vm._select_command is None
    assert vm._deselect_command is None
    assert vm._select_next_command is None
    assert vm._select_previous_command is None
    assert vm._reconstruct_command is None

    # Accessing a property builds and caches exactly that command.
    cmd = vm.select_next_command
    assert cmd is not None
    assert vm._select_next_command is cmd
    # Other slots remain unbuilt.
    assert vm._select_command is None

    # Repeated access returns the same cached instance (stable identity —
    # forwarding VMs rely on this).
    assert vm.select_next_command is cmd
    vm.dispose()


def test_lazy_command_preserves_status_trigger_wiring() -> None:
    vm = _leaf()
    fired = 0

    def _inc(_: object) -> None:
        nonlocal fired
        fired += 1

    # Access (build) the command, subscribe, then transition the lifecycle.
    vm.select_command.can_execute_changed.subscribe(on_next=_inc)
    vm.construct()  # Constructing -> Constructed: status trigger emits

    assert fired > 0, "lazily-built command must still fire can_execute_changed on status change"
    vm.dispose()


def test_dispose_without_accessing_commands_is_safe() -> None:
    vm = _leaf()
    # Never touch the command properties — dispose must not blow up on the
    # un-built (None) slots.
    vm.construct()
    vm.dispose()
