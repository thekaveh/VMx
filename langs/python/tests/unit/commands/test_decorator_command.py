"""Unit tests for DecoratorCommand behavior not covered by CMDD-* in the
conformance catalog (e.g., exception handling semantics on inner.execute).
"""

from __future__ import annotations

import pytest

from vmx.commands import DecoratorCommand, RelayCommandBuilder


def _build_throwing() -> object:
    def _raise() -> None:
        raise RuntimeError("boom")

    return RelayCommandBuilder().task(_raise).predicate(lambda: True).build()


def test_post_execute_runs_even_when_inner_raises() -> None:
    log: list[str] = []
    dec = DecoratorCommand(
        _build_throwing(),
        pre_execute=lambda: log.append("pre"),
        post_execute=lambda: log.append("post"),
    )

    with pytest.raises(RuntimeError, match="boom"):
        dec.execute()

    assert log == ["pre", "post"], "post_execute must run even if inner raises"


def test_decorator_dispose_is_idempotent() -> None:
    """Teardown parity with the C# IDisposable surface."""
    inner = RelayCommandBuilder().task(lambda: None).build()
    deco = DecoratorCommand(inner)
    deco.dispose()
    deco.dispose()


def test_confirmation_decorator_dispose_is_idempotent() -> None:
    from vmx.commands.confirmation_decorator_command import ConfirmationDecoratorCommand

    async def _yes() -> bool:
        return True

    inner = RelayCommandBuilder().task(lambda: None).build()
    deco = ConfirmationDecoratorCommand(inner, _yes)
    deco.dispose()
    deco.dispose()
