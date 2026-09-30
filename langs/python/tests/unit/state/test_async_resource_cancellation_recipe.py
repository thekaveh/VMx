"""Executable form of the loader-cancellation recipe (#334).

The block between the recipe markers is shown verbatim, dedented, in
docs/content/primitives/state-reactive-helpers.md; tools/tests keeps them equal.
"""

from __future__ import annotations

import asyncio

from vmx import (
    NULL_DISPATCHER,
    AsyncResourceRetention,
    AsyncResourceStatus,
    AsyncResourceVM,
    Message,
    MessageHub,
)


class _Profiles:
    """First request answers; the second is cancelled by another owner."""

    def __init__(self) -> None:
        self._answers = ["ada"]

    def shared_request(self) -> asyncio.Future[str]:
        request: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        if self._answers:
            request.set_result(self._answers.pop(0))
        else:
            asyncio.get_running_loop().call_soon(request.cancel)
        return request


async def test_loader_cancelled_by_another_owner_keeps_the_previous_profile() -> None:
    profiles = _Profiles()
    hub: MessageHub[Message] = MessageHub()
    dispatcher = NULL_DISPATCHER

    # docs-recipe:start
    async def load_profile() -> str:
        # Another owner may cancel the shared request. The CancelledError that
        # reaches this loader settles the VM like Cancel; it never stays Loading.
        return await profiles.shared_request()

    profile = AsyncResourceVM(
        name="profile",
        loader=load_profile,
        hub=hub,
        dispatcher=dispatcher,
        retention=AsyncResourceRetention.RETAIN_PREVIOUS,
    )
    await profile.load()  # Ready("ada")
    await profile.reload()  # the shared request is cancelled mid-flight

    assert profile.state.status is AsyncResourceStatus.READY
    assert profile.state.value == "ada"  # the retained value is restored
    assert profile.reload_command.can_execute()  # the next reload is admitted
    # docs-recipe:end

    profile.dispose()
