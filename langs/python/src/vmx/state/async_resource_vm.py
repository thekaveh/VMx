"""One cancellable asynchronously acquired presentation value.

Spec: spec/23-async-resource-vm.md; ADR-0100.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable
from enum import Enum
from threading import RLock
from typing import Generic, Literal, TypeAlias, TypeVar

from vmx._asyncio_runner import post_to_loop
from vmx.commands.async_relay_command import AsyncRelayCommand
from vmx.commands.relay_command import RelayCommand, _run_disposal_steps
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
    loop: asyncio.AbstractEventLoop
    late_cleanup_registered: bool = False
    cancellation_signalled: bool = False
    result_claimed: bool = False


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
        self._resource_gate = RLock()

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
        with self._resource_gate:
            operation = self._operation
            if not self._can_cancel() or operation is None:
                return
            self._operation_identity += 1
            identity = self._operation_identity
            self._operation = None
            self._state = operation.baseline
        self._cancel_operation(operation)
        # Cancel the old wrappers before rollback observers can admit new work.
        for command in (self._load_command, self._reload_command):
            try:
                command.cancel()
            except BaseException:
                pass
        try:
            self._publish_state(identity, operation.baseline)
        except BaseException:
            # Cancellation is nonthrowing; state rollback remains authoritative.
            pass

    def _can_load(self) -> bool:
        with self._resource_gate:
            return not self._resource_disposed and self._state.status is AsyncResourceStatus.IDLE

    def _can_reload(self) -> bool:
        with self._resource_gate:
            return (
                not self._resource_disposed and self._state.status is not AsyncResourceStatus.IDLE
            )

    def _can_cancel(self) -> bool:
        with self._resource_gate:
            return not self._resource_disposed and self._state.status is AsyncResourceStatus.LOADING

    async def _start(self) -> None:
        with self._resource_gate:
            if self._resource_disposed:
                return
            previous_operation = self._operation
            self._operation = None
            self._operation_identity += 1
            identity = self._operation_identity
            previous: _PresentValue[T] | _AbsentValue = _ABSENT_VALUE
            if self._retention is AsyncResourceRetention.DISCARD_PREVIOUS:
                previous = _value_of(self._stable_state)
                if isinstance(previous, _PresentValue):
                    self._stable_state = AsyncResourceIdle()
        if previous_operation is not None:
            self._cancel_operation(previous_operation)
        if isinstance(previous, _PresentValue):
            self._cleanup(previous.value)

        with self._resource_gate:
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

        # Task factories are executable user hooks: creation must be outside the
        # metadata gate, followed by another admission check.
        loop = asyncio.get_running_loop()
        task = loop.create_task(invoke_loader())
        cancelled: asyncio.Future[None] = loop.create_future()
        operation = _Operation(identity, task, cancelled, baseline, loop)
        with self._resource_gate:
            admitted = not self._resource_disposed and self._operation_identity == identity
            if admitted:
                self._operation = operation
                self._state = loading
        if not admitted:
            self._cancel_operation(operation)
            return
        try:
            self._publish_state(identity, loading)
        except BaseException:
            self._rollback(operation)
            self._cancel_operation(operation)
            raise

        try:
            done, _pending = await asyncio.wait(
                (task, cancelled), return_when=asyncio.FIRST_COMPLETED
            )
        except asyncio.CancelledError:
            self._rollback(operation)
            self._cancel_operation(operation)
            raise

        if cancelled in done:
            self._register_late_cleanup(operation)
            return
        self._consume_result(operation, accept=True)

    def _rollback(self, operation: _Operation[T]) -> None:
        with self._resource_gate:
            if not self._is_operation_current(operation):
                return
            self._operation_identity += 1
            identity = self._operation_identity
            self._operation = None
            self._state = operation.baseline
        try:
            self._publish_state(identity, operation.baseline)
        except BaseException:
            # Preserve the primary exception/cancellation after authoritative rollback.
            pass

    def _is_operation_current(self, operation: _Operation[T]) -> bool:
        # Call only while holding _resource_gate.
        return (
            not self._resource_disposed
            and self._operation_identity == operation.identity
            and self._operation is operation
        )

    def _consume_result(self, operation: _Operation[T], *, accept: bool = False) -> None:
        try:
            value = operation.task.result()
        except asyncio.CancelledError:
            return
        except BaseException as error:
            with self._resource_gate:
                if operation.result_claimed:
                    return
                operation.result_claimed = True
                if not accept or not self._is_operation_current(operation):
                    return
                self._operation = None
                previous = (
                    _value_of(self._stable_state)
                    if self._retention is AsyncResourceRetention.RETAIN_PREVIOUS
                    else _ABSENT_VALUE
                )
                failed: StableAsyncResourceState[T]
                if isinstance(previous, _PresentValue):
                    failed = AsyncResourceErrorWithValue(previous.value, error)
                else:
                    failed = AsyncResourceError(error)
                self._stable_state = failed
                self._state = failed
            self._publish_state(operation.identity, failed)
            return

        with self._resource_gate:
            if operation.result_claimed:
                return
            operation.result_claimed = True
            admitted = accept and self._is_operation_current(operation)
            previous = _ABSENT_VALUE
            ready: StableAsyncResourceState[T] = AsyncResourceReady(value)
            if admitted:
                self._operation = None
                previous = _value_of(self._stable_state)
                self._stable_state = ready
                self._state = ready
        if not admitted:
            self._cleanup(value)
            return
        if isinstance(previous, _PresentValue):
            self._cleanup(previous.value)
        self._publish_state(operation.identity, ready)

    def _on_operation_loop(self, operation: _Operation[T], action: Callable[[], None]) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is operation.loop:
            action()
        elif not post_to_loop(operation.loop, action) and operation.task.done():
            # Closed terminal tasks can be inspected, but never mutated or
            # registered with a dead loop. Pending work cannot be drained here.
            self._consume_result(operation)

    def _cancel_operation(self, operation: _Operation[T]) -> None:
        def cancel_on_owner() -> None:
            self._register_on_owner(operation)
            if operation.cancellation_signalled:
                return
            operation.cancellation_signalled = True
            if not operation.cancelled.done():
                operation.cancelled.set_result(None)
            if not operation.task.done():
                operation.task.cancel()

        self._on_operation_loop(operation, cancel_on_owner)

    def _register_on_owner(self, operation: _Operation[T]) -> None:
        if operation.late_cleanup_registered:
            return
        operation.task.add_done_callback(lambda _task: self._consume_result(operation))
        operation.late_cleanup_registered = True

    def _register_late_cleanup(self, operation: _Operation[T]) -> None:
        self._on_operation_loop(operation, lambda: self._register_on_owner(operation))

    def _publish_state(self, identity: int, state: AsyncResourceState[T]) -> None:
        def publish(action: Callable[[], None]) -> None:
            with self._resource_gate:
                if (
                    self._resource_disposed
                    or self._operation_identity != identity
                    or self._state is not state
                ):
                    return
                # This individual publication is admitted here. Ordinary base
                # notification delivery may finish after concurrent invalidation.
            action()

        _run_disposal_steps(
            lambda: publish(lambda: self._notify_property_changed("state")),
            lambda: publish(self._load_command.raise_can_execute_changed),
            lambda: publish(self._reload_command.raise_can_execute_changed),
            lambda: publish(self._cancel_command.raise_can_execute_changed),
        )

    def _cleanup(self, value: T) -> None:
        if self._cleanup_value is None:
            return
        try:
            self._cleanup_value(value)
        except BaseException:
            pass

    def _on_dispose(self) -> None:
        with self._resource_gate:
            if self._resource_disposed:
                return
            self._resource_disposed = True
            self._operation_identity += 1
            operation = self._operation
            self._operation = None
            accepted = _value_of(self._stable_state)
            self._stable_state = AsyncResourceIdle()
        steps: list[Callable[[], None]] = []
        if operation is not None:
            steps.append(lambda: self._cancel_operation(operation))
        steps.extend(
            (
                self._load_command.cancel,
                self._reload_command.cancel,
                self._load_command.dispose,
                self._reload_command.dispose,
                self._cancel_command.dispose,
            )
        )
        if isinstance(accepted, _PresentValue):
            steps.append(lambda: self._cleanup(accepted.value))
        _run_disposal_steps(*steps)
