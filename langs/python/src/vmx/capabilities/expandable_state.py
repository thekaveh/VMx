"""ExpandableState — composition-friendly helper for expand/collapse.

See spec/05-component-vm.md §8 (IExpandable integration), ADR-0015 and
ADR-0159 (expansion commands).
"""

from __future__ import annotations

from collections.abc import Callable

from reactivex import Observable
from reactivex import operators as ops
from reactivex.subject import Subject

from vmx._disposal import _run_disposal_steps
from vmx.capabilities.expansion import (
    ICollapsible,
    IExpandable,
    IExpansionTogglable,
)
from vmx.commands.relay_command import RelayCommand


class ExpandableState(IExpandable, ICollapsible, IExpansionTogglable):
    """Bundle of IExpandable + ICollapsible + IExpansionTogglable with a
    change observable and the matching commands. Compose into VMs that want
    expand/collapse."""

    def __init__(self, initially_expanded: bool = False) -> None:
        self._is_expanded = initially_expanded
        self._changes: Subject[bool] = Subject()
        self._disposed = False
        # Built on first read (ADR-0159), so a helper whose commands are never
        # read holds no trigger subscriptions and disposal creates none.
        self._expand_command: RelayCommand | None = None
        self._collapse_command: RelayCommand | None = None
        self._toggle_expansion_command: RelayCommand | None = None

    @property
    def is_expanded(self) -> bool:
        return self._is_expanded

    @property
    def is_expanded_changed(self) -> Observable[bool]:
        return self._changes.pipe(ops.as_observable())

    @property
    def expand_command(self) -> RelayCommand:
        """Runs :meth:`expand` when :meth:`can_expand` is true.

        This helper owns the command: :meth:`dispose` disposes it, and callers
        must not.
        """
        if self._expand_command is None:
            self._expand_command = self._build_command(self.can_expand, self.expand)
        return self._expand_command

    @property
    def collapse_command(self) -> RelayCommand:
        """Runs :meth:`collapse` when :meth:`can_collapse` is true.

        This helper owns the command: :meth:`dispose` disposes it, and callers
        must not.
        """
        if self._collapse_command is None:
            self._collapse_command = self._build_command(self.can_collapse, self.collapse)
        return self._collapse_command

    @property
    def toggle_expansion_command(self) -> RelayCommand:
        """Runs :meth:`toggle_expansion` when :meth:`can_toggle_expansion` is true.

        This helper owns the command: :meth:`dispose` disposes it, and callers
        must not.
        """
        if self._toggle_expansion_command is None:
            self._toggle_expansion_command = self._build_command(
                self.can_toggle_expansion, self.toggle_expansion
            )
        return self._toggle_expansion_command

    def can_expand(self) -> bool:
        return not self._is_expanded

    def expand(self) -> None:
        if self._disposed:
            return
        if self._is_expanded:
            return
        self._is_expanded = True
        self._changes.on_next(True)

    def can_collapse(self) -> bool:
        return self._is_expanded

    def collapse(self) -> None:
        if self._disposed:
            return
        if not self._is_expanded:
            return
        self._is_expanded = False
        self._changes.on_next(False)

    def can_toggle_expansion(self) -> bool:
        return True

    def toggle_expansion(self) -> None:
        if self._is_expanded:
            self.collapse()
        else:
            self.expand()

    def dispose(self) -> None:
        """Dispose the commands that were read, then complete and dispose the
        change observable. Idempotent."""
        if self._disposed:
            return
        self._disposed = True
        # A raising observer must not skip a later step (#768).
        commands = (
            self._expand_command,
            self._collapse_command,
            self._toggle_expansion_command,
        )
        _run_disposal_steps(
            *(command.dispose for command in commands if command is not None),
            self._changes.on_completed,
            self._changes.dispose,
        )

    def _build_command(
        self, predicate: Callable[[], bool], task: Callable[[], None]
    ) -> RelayCommand:
        # A command read after disposal is built without the disposed trigger
        # subject and disposed at once, so it is inert like the others (ADR-0068).
        builder = RelayCommand.builder().predicate(predicate).task(task)
        if not self._disposed:
            trigger: Observable[object] = self._changes
            builder = builder.triggers(trigger)
        command = builder.build()
        if self._disposed:
            command.dispose()
        return command
