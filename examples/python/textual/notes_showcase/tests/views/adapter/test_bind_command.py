"""Unit tests for :func:`notes_showcase.views.adapter.bind_command` (plan §4.b)."""

from __future__ import annotations

from reactivex.subject import Subject

from textual.widgets import Button

from vmx.commands.relay_command import RelayCommand

from notes_showcase.views.adapter import bind_command


def _build_command(
    *,
    predicate_state: list[bool],
    invocations: list[int],
    trigger: Subject[object],
) -> RelayCommand:
    """RelayCommand whose predicate consults *predicate_state[0]* and whose task
    records into *invocations*. *trigger* is the can_execute_changed source."""

    return (
        RelayCommand.builder()
        .predicate(lambda: predicate_state[0])
        .task(lambda: invocations.append(1))
        .triggers(trigger)
        .build()
    )


def test_bind_command_seeds_disabled_from_can_execute() -> None:
    state = [True]
    invocations: list[int] = []
    trigger: Subject[object] = Subject()
    cmd = _build_command(
        predicate_state=state, invocations=invocations, trigger=trigger
    )
    button = Button("go")

    sub = bind_command(button, cmd)
    try:
        assert button.disabled is False
    finally:
        sub.dispose()
        cmd.dispose()


def test_bind_command_button_press_executes_command() -> None:
    state = [True]
    invocations: list[int] = []
    trigger: Subject[object] = Subject()
    cmd = _build_command(
        predicate_state=state, invocations=invocations, trigger=trigger
    )
    button = Button("go")

    sub = bind_command(button, cmd)
    try:
        button.action_press()  # type: ignore[misc]
        assert invocations == [1]
    finally:
        sub.dispose()
        cmd.dispose()


def test_bind_command_tracks_can_execute_flipping_to_false() -> None:
    state = [True]
    invocations: list[int] = []
    trigger: Subject[object] = Subject()
    cmd = _build_command(
        predicate_state=state, invocations=invocations, trigger=trigger
    )
    button = Button("go")

    sub = bind_command(button, cmd)
    try:
        assert button.disabled is False
        state[0] = False
        trigger.on_next(object())  # tell the command to re-evaluate
        assert button.disabled is True
    finally:
        sub.dispose()
        cmd.dispose()


def test_bind_command_tracks_can_execute_flipping_back_to_true() -> None:
    state = [False]
    invocations: list[int] = []
    trigger: Subject[object] = Subject()
    cmd = _build_command(
        predicate_state=state, invocations=invocations, trigger=trigger
    )
    button = Button("go")

    sub = bind_command(button, cmd)
    try:
        assert button.disabled is True
        state[0] = True
        trigger.on_next(object())
        assert button.disabled is False
    finally:
        sub.dispose()
        cmd.dispose()


def test_bind_command_dispose_unsubscribes() -> None:
    state = [True]
    invocations: list[int] = []
    trigger: Subject[object] = Subject()
    cmd = _build_command(
        predicate_state=state, invocations=invocations, trigger=trigger
    )
    button = Button("go")
    sub = bind_command(button, cmd)
    sub.dispose()

    state[0] = False
    trigger.on_next(object())
    # disabled was frozen at sub-dispose time → still False
    assert button.disabled is False
    cmd.dispose()
