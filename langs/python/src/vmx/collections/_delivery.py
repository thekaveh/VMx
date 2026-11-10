"""Shared local-then-hub delivery for the hub-publishing collections.

See spec/01-concepts.md §1.4, spec/21-collections.md §2.5 and ADR-0171.
"""

from __future__ import annotations

from collections.abc import Callable


def deliver_then_publish(deliver: Callable[[], None], publish: Callable[[], None]) -> None:
    """Run the local delivery, then the hub publication, for one committed change.

    A failing local subscriber does not suppress the hub message: *publish*
    still runs, and the first failure is re-raised afterwards. This mirrors
    the failure rule of
    ``vmx.components._container_helpers.deliver_collection_changed``.

    Unlike that helper, this one has no disposal check: *publish* always runs.
    A collection that a local subscriber can dispose during delivery makes
    *publish* skip the hub send once it is disposed, as
    ``ObservableDictionary`` does (#1431).
    """
    first_error: BaseException | None = None
    try:
        deliver()
    except BaseException as error:
        first_error = error
    try:
        publish()
    except BaseException as error:
        if first_error is None:
            first_error = error
    if first_error is not None:
        raise first_error


def first_failure(*steps: Callable[[], object]) -> BaseException | None:
    """Run every step and return the first failure instead of raising it.

    The dictionary runs its key-view updates through this helper, so a
    raising key-view subscriber skips neither the other key view nor the
    dictionary's own events and hub message. The caller re-raises the failure
    after those (#1430).
    """
    failure: BaseException | None = None
    for step in steps:
        try:
            step()
        except BaseException as error:
            if failure is None:
                failure = error
    return failure


def notify_then_raise(earlier: BaseException | None, notify: Callable[[], None]) -> None:
    """Run *notify*, then re-raise *earlier*, or else the failure of *notify*.

    *earlier* is a failure that happened before *notify* started, so it takes
    precedence (#1430).
    """
    try:
        notify()
    except BaseException:
        if earlier is None:
            raise
    if earlier is not None:
        raise earlier
