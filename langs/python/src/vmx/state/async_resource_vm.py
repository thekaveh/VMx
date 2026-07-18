"""One cancellable asynchronously acquired presentation value.

Spec: spec/23-async-resource-vm.md; ADR-0100.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Generic, Literal, TypeAlias, TypeVar

from vmx.commands.async_relay_command import AsyncRelayCommand
from vmx.commands.relay_command import RelayCommand
from vmx.components.base import _ComponentVMBase
from vmx.components.protocols import ViewModelType
from vmx.messages.protocols import Message
from vmx.services.dispatcher import Dispatcher
from vmx.services.message_hub import MessageHubProto

T = TypeVar("T")


class AsyncResourceStatus(str, Enum):
    IDLE = "Idle"
    LOADING = "Loading"
    READY = "Ready"
    ERROR = "Error"


class AsyncResourceRetention(str, Enum):
    DISCARD_PREVIOUS = "DiscardPrevious"
    RETAIN_PREVIOUS = "RetainPrevious"


@dataclasses.dataclass(frozen=True)
class AsyncResourceIdle(Generic[T]):
    status: Literal[AsyncResourceStatus.IDLE] = dataclasses.field(
        default=AsyncResourceStatus.IDLE, init=False
    )


@dataclasses.dataclass(frozen=True)
class AsyncResourceLoading(Generic[T]):
    status: Literal[AsyncResourceStatus.LOADING] = dataclasses.field(
        default=AsyncResourceStatus.LOADING, init=False
    )


@dataclasses.dataclass(frozen=True)
class AsyncResourceLoadingWithValue(Generic[T]):
    value: T
    status: Literal[AsyncResourceStatus.LOADING] = dataclasses.field(
        default=AsyncResourceStatus.LOADING, init=False
    )


@dataclasses.dataclass(frozen=True)
class AsyncResourceReady(Generic[T]):
    value: T
    status: Literal[AsyncResourceStatus.READY] = dataclasses.field(
        default=AsyncResourceStatus.READY, init=False
    )


@dataclasses.dataclass(frozen=True)
class AsyncResourceError(Generic[T]):
    error: BaseException
    status: Literal[AsyncResourceStatus.ERROR] = dataclasses.field(
        default=AsyncResourceStatus.ERROR, init=False
    )


@dataclasses.dataclass(frozen=True)
class AsyncResourceErrorWithValue(Generic[T]):
    value: T
    error: BaseException
    status: Literal[AsyncResourceStatus.ERROR] = dataclasses.field(
        default=AsyncResourceStatus.ERROR, init=False
    )


AsyncResourceState: TypeAlias = (
    AsyncResourceIdle[T]
    | AsyncResourceLoading[T]
    | AsyncResourceLoadingWithValue[T]
    | AsyncResourceReady[T]
    | AsyncResourceError[T]
    | AsyncResourceErrorWithValue[T]
)
StableAsyncResourceState: TypeAlias = (
    AsyncResourceIdle[T]
    | AsyncResourceReady[T]
    | AsyncResourceError[T]
    | AsyncResourceErrorWithValue[T]
)


@dataclasses.dataclass(frozen=True)
class _PresentValue(Generic[T]):
    value: T


@dataclasses.dataclass(frozen=True)
class _AbsentValue:
    pass


_ABSENT_VALUE = _AbsentValue()


@dataclasses.dataclass
class _Operation(Generic[T]):
    identity: int
    task: asyncio.Task[T]
    cancelled: asyncio.Future[None]
    baseline: StableAsyncResourceState[T]
    late_cleanup_registered: bool = False


def _value_of(state: StableAsyncResourceState[T]) -> _PresentValue[T] | _AbsentValue:
    if isinstance(state, AsyncResourceReady | AsyncResourceErrorWithValue):
        return _PresentValue(state.value)
    return _ABSENT_VALUE


class AsyncResourceVM(Generic[T], _ComponentVMBase):
    """Component viewmodel for one cancellable asynchronously acquired value."""

    def __init__(
        self,
        *,
        name: str,
        loader: Callable[[], Awaitable[T]],
        hub: MessageHubProto[Message],
        dispatcher: Dispatcher,
        hint: str = "",
        retention: AsyncResourceRetention = AsyncResourceRetention.DISCARD_PREVIOUS,
        cleanup_value: Callable[[T], None] | None = None,
    ) -> None:
        super().__init__(
            name=name,
            hint=hint,
            hub=hub,
            dispatcher=dispatcher,
        )
        self._loader = loader
        self._retention = retention
        self._cleanup_value = cleanup_value
        self._state: AsyncResourceState[T] = AsyncResourceIdle()
        self._stable_state: StableAsyncResourceState[T] = AsyncResourceIdle()
        self._operation_identity = 0
        self._operation: _Operation[T] | None = None
        self._resource_disposed = False

        self._load_command = (
            AsyncRelayCommand.builder().task(self.load).predicate(self._can_load).build()
        )
        self._reload_command = (
            AsyncRelayCommand.builder().task(self.reload).predicate(self._can_reload).build()
        )
        self._cancel_command = (
            RelayCommand.builder().task(self.cancel).predicate(self._can_cancel).build()
        )

    @property
    def type(self) -> ViewModelType:
        return ViewModelType.COMPONENT

    @property
    def state(self) -> AsyncResourceState[T]:
        return self._state

    @property
    def load_command(self) -> AsyncRelayCommand:
        return self._load_command

    @property
    def reload_command(self) -> AsyncRelayCommand:
        return self._reload_command

    @property
    def cancel_command(self) -> RelayCommand:
        return self._cancel_command

    async def load(self) -> None:
        if not self._can_load():
            return
        await self._start()

    async def reload(self) -> None:
        if not self._can_reload():
            return
        await self._start()

    def cancel(self) -> None:
        operation = self._operation
        if not self._can_cancel() or operation is None:
            return
        self._operation_identity += 1
        self._operation = None
        self._cancel_operation(operation)
        self._set_state(operation.baseline)
        self._load_command.cancel()
        self._reload_command.cancel()

    def _can_load(self) -> bool:
        return not self._resource_disposed and self._state.status is AsyncResourceStatus.IDLE

    def _can_reload(self) -> bool:
        return not self._resource_disposed and self._state.status is not AsyncResourceStatus.IDLE

    def _can_cancel(self) -> bool:
        return not self._resource_disposed and self._state.status is AsyncResourceStatus.LOADING

    async def _start(self) -> None:
        previous_operation = self._operation
        self._operation_identity += 1
        identity = self._operation_identity

        if self._retention is AsyncResourceRetention.DISCARD_PREVIOUS:
            previous = _value_of(self._stable_state)
            if isinstance(previous, _PresentValue):
                self._stable_state = AsyncResourceIdle()
                self._cleanup(previous.value)

        # Cleanup is user code and may dispose the VM or start a newer intent.
        # Do not create (and therefore invoke) a loader after either terminal
        # transition has superseded this start.
        if self._resource_disposed or self._operation_identity != identity:
            return

        baseline = self._stable_state
        retained = (
            _value_of(baseline)
            if self._retention is AsyncResourceRetention.RETAIN_PREVIOUS
            else _ABSENT_VALUE
        )
        loading: AsyncResourceState[T]
        if isinstance(retained, _PresentValue):
            loading = AsyncResourceLoadingWithValue(retained.value)
        else:
            loading = AsyncResourceLoading()

        async def invoke_loader() -> T:
            return await self._loader()

        task = asyncio.create_task(invoke_loader())
        cancelled: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        operation = _Operation(identity, task, cancelled, baseline)
        self._operation = operation
        if previous_operation is not None:
            self._cancel_operation(previous_operation)
        self._set_state(loading)

        try:
            done, _pending = await asyncio.wait(
                (task, cancelled), return_when=asyncio.FIRST_COMPLETED
            )
        except asyncio.CancelledError:
            if self._is_operation_current(operation):
                self._operation_identity += 1
                self._operation = None
                self._cancel_operation(operation)
                self._set_state(baseline)
            self._register_late_cleanup(operation)
            raise

        if cancelled in done:
            self._register_late_cleanup(operation)
            return

        try:
            value = task.result()
        except asyncio.CancelledError:
            return
        except BaseException as error:
            if not self._is_operation_current(operation):
                return
            self._operation = None
            if self._retention is AsyncResourceRetention.RETAIN_PREVIOUS:
                previous = _value_of(self._stable_state)
            else:
                previous = _ABSENT_VALUE
            failed: StableAsyncResourceState[T]
            if isinstance(previous, _PresentValue):
                failed = AsyncResourceErrorWithValue(previous.value, error)
            else:
                failed = AsyncResourceError(error)
            self._stable_state = failed
            self._set_state(failed)
            return

        if not self._is_operation_current(operation):
            self._cleanup(value)
            return

        self._operation = None
        previous = _value_of(self._stable_state)
        ready: StableAsyncResourceState[T] = AsyncResourceReady(value)
        self._stable_state = ready
        if isinstance(previous, _PresentValue):
            self._cleanup(previous.value)
        self._set_state(ready)

    def _is_operation_current(self, operation: _Operation[T]) -> bool:
        return (
            not self._resource_disposed
            and self._operation_identity == operation.identity
            and self._operation is operation
        )

    @staticmethod
    def _cancel_operation(operation: _Operation[T]) -> None:
        if not operation.cancelled.done():
            operation.cancelled.set_result(None)
        if not operation.task.done():
            operation.task.cancel()

    def _cleanup_late_task(self, task: asyncio.Task[T]) -> None:
        try:
            value = task.result()
        except BaseException:
            return
        self._cleanup(value)

    def _register_late_cleanup(self, operation: _Operation[T]) -> None:
        if operation.late_cleanup_registered:
            return
        operation.late_cleanup_registered = True
        operation.task.add_done_callback(self._cleanup_late_task)

    def _set_state(self, state: AsyncResourceState[T]) -> None:
        if self._resource_disposed or self._state is state:
            return
        self._state = state
        self._notify_property_changed("state")
        self._load_command.raise_can_execute_changed()
        self._reload_command.raise_can_execute_changed()
        self._cancel_command.raise_can_execute_changed()

    def _cleanup(self, value: T) -> None:
        if self._cleanup_value is None:
            return
        try:
            self._cleanup_value(value)
        except BaseException:
            pass

    def _on_dispose(self) -> None:
        if self._resource_disposed:
            return
        self._resource_disposed = True
        self._operation_identity += 1
        operation = self._operation
        self._operation = None
        if operation is not None:
            self._cancel_operation(operation)
            self._register_late_cleanup(operation)
        self._load_command.cancel()
        self._reload_command.cancel()
        self._load_command.dispose()
        self._reload_command.dispose()
        self._cancel_command.dispose()
        accepted = _value_of(self._stable_state)
        self._stable_state = AsyncResourceIdle()
        if isinstance(accepted, _PresentValue):
            self._cleanup(accepted.value)
