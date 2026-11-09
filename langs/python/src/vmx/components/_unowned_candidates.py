"""Disposal of the candidates that a failed population built (#1324)."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress

from vmx.components.base import _ComponentVMBase, _ParentCompositeVM
from vmx.components.protocols import ComponentVMProto


def dispose_unowned_candidates(
    parent: _ParentCompositeVM, candidates: Iterable[ComponentVMProto | None]
) -> None:
    """Dispose each candidate of a failed population that nobody owns.

    A population fails when a later factory or projector raises, or when its
    preflight refuses it before the commit. A candidate that has a parent, that
    another ownership transaction holds, or that is an owner on the ancestor
    chain of *parent*, belongs to someone else and is skipped. Each canonical
    identity is disposed once. The disposal is best-effort: the population's
    own failure is the one that propagates.

    The parent and in-progress checks take no lock. If another thread starts
    to attach a candidate after the checks, this cleanup can still dispose it.
    A factory's fresh output is normally reachable only by the failed
    population, so the window is narrow.
    """
    seen: set[int] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        identity: object = candidate
        if isinstance(candidate, _ComponentVMBase):
            identity = candidate._ownership_identity
            if candidate._ownership_parent is not None or identity._ownership_in_progress:
                seen.add(id(identity))
                continue
        if id(identity) in seen:
            continue
        seen.add(id(identity))
        if _owns_on_chain(parent, identity):
            continue
        with suppress(Exception):
            candidate.dispose()


def _owns_on_chain(parent: _ParentCompositeVM, identity: object) -> bool:
    cursor: _ParentCompositeVM | None = parent
    while cursor is not None:
        if cursor.owner._ownership_identity is identity:
            return True
        cursor = cursor.owner_parent
    return False
