"""Static typing of ``_own`` (spec/02 §2.3).

``_own`` returns the resource so an owned field can be assigned inline. These
tests run ``mypy --strict`` over a small consumer module: the return type must
be the argument's own type, not the accepted-shape union.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from mypy import api as mypy_api

_PRELUDE = """\
from __future__ import annotations

from collections.abc import Callable

from reactivex.abc import DisposableBase
from reactivex.subject import Subject

from vmx.commands import RelayCommand
from vmx.components import ComponentVM
from vmx.services import MessageHub, RxDispatcher


class PanelVM(ComponentVM):
    def __init__(self) -> None:
        super().__init__(
            name="panel", hint="", hub=MessageHub(), dispatcher=RxDispatcher.immediate()
        )
"""


def _run_mypy(tmp_path: Path, body: str) -> tuple[int, str]:
    module = tmp_path / "consumer.py"
    module.write_text(_PRELUDE + textwrap.indent(textwrap.dedent(body), " " * 8))
    stdout, stderr, status = mypy_api.run(
        ["--strict", "--no-incremental", "--cache-dir", str(tmp_path / ".mypy_cache"), str(module)]
    )
    return status, stdout + stderr


def test_own_returns_the_argument_type_under_strict_mypy(tmp_path: Path) -> None:
    status, output = _run_mypy(
        tmp_path,
        """
        self.save_command: RelayCommand = self._own(
            RelayCommand.builder().task(lambda: None).build()
        )
        self.subscription: DisposableBase = self._own(Subject[int]().subscribe(print))
        self.release: Callable[[], None] = self._own(lambda: None)
        """,
    )

    assert status == 0, output


def test_own_rejects_an_assignment_to_an_unrelated_type(tmp_path: Path) -> None:
    status, output = _run_mypy(
        tmp_path,
        """
        self.count: int = self._own(lambda: None)
        """,
    )

    assert status == 1, output
    assert "Incompatible types in assignment" in output
