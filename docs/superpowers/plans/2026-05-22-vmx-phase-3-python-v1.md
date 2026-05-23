# VMx Phase 3 — Python v1.0.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Python flavor of VMx at `langs/python/`, satisfying `spec-v1.0.0` end-to-end and passing all 68 conformance IDs. Tag `python-v1.0.0` when done. Mirror the C# v1.0.0 behavior contract; idiomatic Python style.

**Architecture:** TDD per sub-module. Each module is a self-contained slice (lifecycle, messages, services, commands, components, composites, groups, aggregates, forwarding) with its own unit tests + contributions to the conformance suite. Python idioms: `snake_case` members, `Protocol` for interfaces, `@dataclass(frozen=True)` for immutable builders, `asyncio` for async, `reactivex` for Rx. Pure Python — no compiled extensions.

**Tech Stack:**

- **Python 3.10+** (matrix 3.10/3.11/3.12/3.13 in CI)
- **reactivex 4.0+** (Rx port; mirrors System.Reactive semantics)
- **pytest** + `pytest-asyncio` + `pytest-cov` for tests
- **mypy --strict** for type checking
- **ruff** for lint + format
- **hatchling** as build backend

**Spec reference:** `/Users/kaveh/repos/VMx/spec/`. Implementers MUST consult the relevant spec file for each module's normative behavior — this plan provides shape and test scaffolding, not the full semantic definition.

**Conformance reference:** The C# implementation under `/Users/kaveh/repos/VMx/langs/csharp/` is the working reference for v1.0.0 — when in doubt about a behavior, look at how the C# library does it. Python should be semantically equivalent.

**Working directory for all relative paths:** `/Users/kaveh/repos/VMx`

______________________________________________________________________

## Commit-message convention (IMPORTANT — same as Phase 2)

**Every commit in this plan MUST NOT carry any `Co-Authored-By: Claude …` or other AI-attribution trailer.** Use commit messages exactly as written in each task — no extra trailers.

______________________________________________________________________

## Pre-flight

```bash
cd /Users/kaveh/repos/VMx
git log --oneline -3
git status
```

Expected: on branch `feat/phase-3-python-v1` (or descended from `0a1b1cf`); working tree clean.

**Tools required:**

```bash
python3 --version    # 3.10+
uv --version
git --version
pre-commit --version
```

______________________________________________________________________

## File structure produced by Phase 3

The Python flavor's package structure is already scaffolded from Phase 0 (`langs/python/src/vmx/` exists with `__init__.py`, `__about__.py`, `py.typed`, and stub `messages/` and `services/` directories). Phase 3 fills the rest in.

```
langs/python/
├── pyproject.toml                                MODIFIED (bump version to 1.0.0, ensure deps)
├── tox.ini                                       KEPT
├── README.md                                     KEPT
├── CHANGELOG.md                                  MODIFIED (add 1.0.0 entry)
├── src/
│   └── vmx/
│       ├── __init__.py                           MODIFIED (re-exports for public API)
│       ├── __about__.py                          MODIFIED (bump __version__ to 1.0.0; __min_spec_version__ = "1.0.0")
│       ├── py.typed                              KEPT (empty marker)
│       ├── lifecycle/
│       │   ├── __init__.py                       NEW (re-exports)
│       │   ├── status.py                         NEW (ConstructionStatus enum)
│       │   ├── exceptions.py                     NEW (StatusTransitionError)
│       │   └── transition_validator.py           NEW (loads spec/fixtures/lifecycle-transitions.json)
│       ├── messages/
│       │   ├── __init__.py                       MODIFIED (re-export all)
│       │   ├── protocols.py                      KEPT (Message, TypedMessage)
│       │   ├── property_changed.py               NEW (PropertyChangedMessage dataclass)
│       │   └── construction_status.py            NEW (ConstructionStatusChangedMessage)
│       ├── services/
│       │   ├── __init__.py                       MODIFIED (re-export all)
│       │   ├── message_hub.py                    MODIFIED (add concrete MessageHub class)
│       │   └── dispatcher.py                     NEW (Dispatcher Protocol + RxDispatcher)
│       ├── commands/
│       │   ├── __init__.py                       NEW
│       │   ├── protocols.py                      NEW (Command, ParameterizedCommand Protocols)
│       │   ├── relay_command.py                  NEW (RelayCommand + RelayCommandOfT + builders)
│       ├── components/
│       │   ├── __init__.py                       NEW
│       │   ├── protocols.py                      NEW (ComponentVM, ComponentVMOf, ReadonlyComponentVMOf Protocols + ViewModelType enum)
│       │   ├── base.py                           NEW (_ComponentVMBase abstract)
│       │   ├── component_vm.py                   NEW (ComponentVM, ComponentVMOf)
│       │   ├── readonly_component_vm.py          NEW (ReadonlyComponentVMOf)
│       │   └── builders.py                       NEW (ComponentVMBuilder, etc.)
│       ├── composites/
│       │   ├── __init__.py                       NEW
│       │   ├── protocols.py                      NEW
│       │   ├── composite_vm.py                   NEW (CompositeVM, CompositeVMOf)
│       │   └── builders.py                       NEW
│       ├── groups/
│       │   ├── __init__.py                       NEW
│       │   ├── group_vm.py                       NEW
│       │   └── builders.py                       NEW
│       ├── aggregates/
│       │   ├── __init__.py                       NEW
│       │   ├── aggregate_vm.py                   NEW (AggregateVM1..AggregateVM5 in one file)
│       │   └── builders.py                       NEW
│       ├── forwarding/
│       │   ├── __init__.py                       NEW
│       │   ├── component.py                      NEW (ForwardingComponentVM)
│       │   └── composite.py                      NEW (ForwardingCompositeVM)
│       └── builders/
│           ├── __init__.py                       NEW
│           └── exceptions.py                     NEW (BuilderValidationError)
└── tests/
    ├── conftest.py                               MODIFIED (shared fixtures)
    ├── unit/
    │   ├── __init__.py                           KEPT
    │   ├── test_smoke.py                         KEPT (Phase 0 tests, still passing)
    │   ├── lifecycle/                            NEW directory
    │   │   ├── __init__.py
    │   │   ├── test_status.py                    NEW
    │   │   ├── test_exceptions.py                NEW
    │   │   └── test_transition_validator.py      NEW
    │   ├── messages/                             NEW directory
    │   │   ├── __init__.py
    │   │   └── test_messages.py                  NEW
    │   ├── services/                             NEW directory
    │   │   ├── __init__.py
    │   │   ├── test_message_hub.py               NEW
    │   │   └── test_rx_dispatcher.py             NEW
    │   ├── commands/                             NEW directory
    │   │   ├── __init__.py
    │   │   └── test_relay_command.py             NEW
    │   ├── components/                           NEW directory
    │   │   ├── __init__.py
    │   │   ├── test_component_vm.py              NEW
    │   │   └── test_readonly_component_vm.py     NEW
    │   ├── composites/
    │   │   ├── __init__.py
    │   │   ├── test_composite_vm.py              NEW
    │   │   └── test_modeled_composite_vm.py      NEW
    │   ├── groups/
    │   │   ├── __init__.py
    │   │   └── test_group_vm.py                  NEW
    │   ├── aggregates/
    │   │   ├── __init__.py
    │   │   └── test_aggregate_vm.py              NEW
    │   ├── forwarding/
    │   │   ├── __init__.py
    │   │   └── test_forwarding.py                NEW
    │   ├── builders/
    │   │   ├── __init__.py
    │   │   └── test_builders.py                  NEW
    │   └── helpers/                              NEW directory
    │       ├── __init__.py
    │       ├── test_hub.py                       NEW (in-memory hub)
    │       ├── test_dispatcher.py                NEW (deterministic scheduler wrapper)
    │       └── recorded_messages.py              NEW (subscriber harness)
    └── conformance/
        ├── __init__.py                           KEPT
        ├── README.md                             KEPT
        ├── fixtures/                             NEW directory
        │   ├── __init__.py
        │   └── loader.py                         NEW (loads spec/fixtures/*.json)
        ├── test_lifecycle.py                     NEW (LIFE-001..013)
        ├── test_hub.py                           NEW (HUB-001..007)
        ├── test_property_change.py               NEW (PROP-001..004)
        ├── test_commands.py                      NEW (CMD-001..007)
        ├── test_component_vm.py                  NEW (CVM-001..006)
        ├── test_composite_vm.py                  NEW (COMP-001..011)
        ├── test_group_vm.py                      NEW (GRP-001..004)
        ├── test_aggregate_vm.py                  NEW (AGG-001..005)
        ├── test_forwarding.py                    NEW (FWD-001..003)
        ├── test_builders.py                      NEW (BLD-001..004)
        └── test_threading.py                     NEW (THR-001..004)

docs/getting-started/
└── python.md                                     NEW

examples/python/
├── hello_vmx/
│   ├── pyproject.toml                            NEW (or just a __main__.py + README)
│   └── __main__.py                               NEW
└── tk_todo_app/
    ├── pyproject.toml                            NEW
    └── (tkinter wiring)                          NEW
```

______________________________________________________________________

## Task organization principles (same as Phase 2)

- One task per module, TDD-driven.
- Each module: source + unit tests + conformance tests in one slice.
- Each task ends with one commit (occasionally two).
- Verification after each task: `uv run pytest`, `uv run mypy --strict src/vmx`, `uv run ruff check`, `uv run ruff format --check`, `pre-commit run` all green.

______________________________________________________________________

## Task 1 — Bootstrap: shared test helpers + fixture loader

**Files:**

- Create: `langs/python/tests/unit/helpers/__init__.py`, `test_hub.py`, `test_dispatcher.py`, `recorded_messages.py`
- Create: `langs/python/tests/conformance/fixtures/__init__.py`, `loader.py`
- Modify: `langs/python/tests/conftest.py` (re-export helpers if needed)

### Step 1.1: TestHub helper

`langs/python/tests/unit/helpers/test_hub.py`:

```python
"""In-process IMessageHub-equivalent for unit tests."""

from __future__ import annotations

from typing import TypeVar

import reactivex as rx
from reactivex.subject import Subject

from vmx.messages.protocols import Message
from vmx.services.message_hub import MessageHub

TMessage = TypeVar("TMessage", bound=Message)


class TestHub(MessageHub[Message]):
    """Subject-backed test hub. Subscribers can use Rx operators directly."""

    def __init__(self) -> None:
        self._subject: Subject[Message] = Subject()

    @property
    def messages(self) -> rx.Observable[Message]:
        return self._subject

    def send(self, message: TMessage) -> None:
        self._subject.on_next(message)

    def dispose(self) -> None:
        self._subject.on_completed()
        self._subject.dispose()
```

### Step 1.2: TestDispatcher helper

`langs/python/tests/unit/helpers/test_dispatcher.py`:

```python
"""IDispatcher-equivalent backed by deterministic Rx test schedulers."""

from __future__ import annotations

import reactivex as rx
from reactivex.testing import TestScheduler

from vmx.services.dispatcher import Dispatcher


class TestDispatcher:
    """Dispatcher with TestScheduler foreground + background for deterministic time."""

    def __init__(self) -> None:
        self.foreground_scheduler: TestScheduler = TestScheduler()
        self.background_scheduler: TestScheduler = TestScheduler()

    @property
    def foreground(self) -> rx.scheduler.SchedulerBase:
        return self.foreground_scheduler

    @property
    def background(self) -> rx.scheduler.SchedulerBase:
        return self.background_scheduler

    def advance_all(self, ticks: int = 1) -> None:
        self.foreground_scheduler.advance_by(ticks)
        self.background_scheduler.advance_by(ticks)
```

(Note: this references types in `vmx.services.message_hub` and `vmx.services.dispatcher` which don't exist yet — those land in Tasks 3 and 4. Task 1 only DEFINES these helpers; they compile but won't import-test until the dependent types exist. Run `python -c "from tests.unit.helpers.test_hub import TestHub"` should fail until Task 3 lands. That's expected.)

Actually — pragma: defer this. To avoid import failures during this phase's intermediate state, write the helpers as Protocol-only references (use `from __future__ import annotations` and rely on string-form type hints). The helpers can be syntactically valid even when the imports fail, as long as you don't INSTANTIATE them in any test until the imports resolve.

Better: put a TYPE_CHECKING guard around the `from vmx....` imports and use string types. Then any test that imports the helper will fail at collection time if the dependent types aren't there — that's exactly what we want during TDD.

### Step 1.3: RecordedMessages helper

`langs/python/tests/unit/helpers/recorded_messages.py`:

```python
"""Test helper: subscribe to an Observable[Message] and record everything."""

from __future__ import annotations

from typing import Generic, TypeVar

import reactivex as rx
import reactivex.operators as ops

from vmx.messages.protocols import Message

TMessage = TypeVar("TMessage", bound=Message)


class RecordedMessages(Generic[TMessage]):
    """Wraps an Observable[Message] subscription. Test code asserts on `.items`."""

    def __init__(self, source: rx.Observable[Message], message_type: type[TMessage]) -> None:
        self.items: list[TMessage] = []
        self._subscription = source.pipe(
            ops.filter(lambda m: isinstance(m, message_type)),
        ).subscribe(self.items.append)

    def dispose(self) -> None:
        self._subscription.dispose()

    def __enter__(self) -> "RecordedMessages[TMessage]":
        return self

    def __exit__(self, *exc: object) -> None:
        self.dispose()
```

### Step 1.4: Conformance fixture loader

`langs/python/tests/conformance/fixtures/loader.py`:

```python
"""Load the JSON fixtures from spec/fixtures/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Resolve repo root: this file is at langs/python/tests/conformance/fixtures/loader.py
# so the repo root is parents[4] from here.
REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURES_DIR = REPO_ROOT / "spec" / "fixtures"


def load(filename: str) -> Any:
    """Load and return the parsed JSON for `filename` in spec/fixtures/."""
    path = FIXTURES_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Fixture not found: {path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)
```

### Step 1.5: Verify + commit

```bash
cd /Users/kaveh/repos/VMx/langs/python
uv sync --all-extras
uv run pytest -v 2>&1 | tail -10
```

Expected: same 4 smoke tests pass; new helper modules don't have their own tests yet so they're not collected as test files.

```bash
cd /Users/kaveh/repos/VMx
git add langs/python/tests/unit/helpers/ langs/python/tests/conformance/fixtures/
git commit -m "test(python): bootstrap helpers — TestHub, TestDispatcher, RecordedMessages, fixture loader

Adds shared test scaffolding that subsequent tasks will use:
- tests/unit/helpers/test_hub.py — Subject-backed in-memory hub
- tests/unit/helpers/test_dispatcher.py — TestScheduler-backed dispatcher
- tests/unit/helpers/recorded_messages.py — subscription-recording context mgr
- tests/conformance/fixtures/loader.py — loads spec/fixtures/*.json

Helpers import types that land in Tasks 2-4; they use TYPE_CHECKING guards
so the package imports cleanly today and the tests fail at the right time
during TDD.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §12.3"
```

Verify trailer:

```bash
git log -1 --format='%B' | grep -i "co-authored" && echo "FAIL" || echo "OK"
```

______________________________________________________________________

## Task 2 — Lifecycle (3a): ConstructionStatus + StatusTransitionError + transition validator + LIFE-001..013

**Spec:** `spec/02-lifecycle.md`, `spec/fixtures/lifecycle-transitions.json`.

### Files

- `langs/python/src/vmx/lifecycle/__init__.py` — re-export `ConstructionStatus`, `StatusTransitionError`, `LifecycleTransitionValidator`.
- `langs/python/src/vmx/lifecycle/status.py` — `ConstructionStatus` enum (IntEnum). Values: `DISPOSED = 0`, `DESTRUCTING = 1`, `DESTRUCTED = 2`, `CONSTRUCTING = 3`, `CONSTRUCTED = 4`.
- `langs/python/src/vmx/lifecycle/exceptions.py` — `StatusTransitionError(RuntimeError)` with attributes `current_status: ConstructionStatus` and `attempted_operation: str`. The message contains both.
- `langs/python/src/vmx/lifecycle/transition_validator.py` — loads `spec/fixtures/lifecycle-transitions.json` once (lazy module-level cache). Exposes:
  - `is_legal(current: ConstructionStatus, operation: str) -> bool`
  - `require(current: ConstructionStatus, operation: str) -> None` (raises `StatusTransitionError` if illegal)
  - `final_state(current: ConstructionStatus, operation: str) -> ConstructionStatus`

The validator can find the fixture file via the same `REPO_ROOT` discovery pattern as the conformance fixture loader (Python `Path(__file__).resolve().parents[N]`). For installed-package scenarios, fall back to a bundled copy: include `lifecycle-transitions.json` as package data in `pyproject.toml` (under `[tool.hatch.build.targets.wheel.shared-data]` or `[tool.hatch.build.force-include]`).

Actually, the cleanest pattern: bundle the JSON into the package itself. Add to `pyproject.toml`:

```toml
[tool.hatch.build.targets.wheel.force-include]
"../../spec/fixtures/lifecycle-transitions.json" = "vmx/lifecycle/_data/lifecycle-transitions.json"
```

Then the validator reads it via `importlib.resources`:

```python
from importlib.resources import files
def _load_table() -> dict[str, list[dict[str, Any]]]:
    data = files("vmx.lifecycle").joinpath("_data/lifecycle-transitions.json").read_text(encoding="utf-8")
    return json.loads(data)
```

This works in installed packages and dev/editable installs alike.

### Unit tests

`tests/unit/lifecycle/test_status.py`:

```python
from vmx.lifecycle.status import ConstructionStatus

def test_construction_status_has_five_values():
    assert len(list(ConstructionStatus)) == 5

def test_disposed_is_zero():
    assert ConstructionStatus.DISPOSED.value == 0
```

`tests/unit/lifecycle/test_exceptions.py`:

```python
import pytest
from vmx.lifecycle.status import ConstructionStatus
from vmx.lifecycle.exceptions import StatusTransitionError

def test_exception_carries_state_and_operation():
    err = StatusTransitionError(ConstructionStatus.DISPOSED, "construct")
    assert err.current_status is ConstructionStatus.DISPOSED
    assert err.attempted_operation == "construct"
    assert "Disposed" in str(err)
    assert "construct" in str(err)
```

`tests/unit/lifecycle/test_transition_validator.py`:

```python
import pytest
from vmx.lifecycle.status import ConstructionStatus
from vmx.lifecycle.exceptions import StatusTransitionError
from vmx.lifecycle.transition_validator import is_legal, require, final_state

@pytest.mark.parametrize("frm,op,expected", [
    (ConstructionStatus.DESTRUCTED, "construct", True),
    (ConstructionStatus.CONSTRUCTED, "destruct", True),
    (ConstructionStatus.CONSTRUCTED, "reconstruct", True),
    (ConstructionStatus.DISPOSED, "construct", False),
    (ConstructionStatus.DISPOSED, "destruct", False),
    (ConstructionStatus.CONSTRUCTING, "construct", False),
])
def test_is_legal_matches_fixture(frm, op, expected):
    assert is_legal(frm, op) == expected

def test_require_raises_with_state_and_op():
    with pytest.raises(StatusTransitionError) as exc_info:
        require(ConstructionStatus.DISPOSED, "construct")
    assert exc_info.value.current_status is ConstructionStatus.DISPOSED
    assert exc_info.value.attempted_operation == "construct"

def test_final_state_returns_expected():
    assert final_state(ConstructionStatus.DESTRUCTED, "construct") is ConstructionStatus.CONSTRUCTED
```

### Conformance tests

`tests/conformance/test_lifecycle.py`:

```python
import pytest
from vmx.lifecycle.status import ConstructionStatus
from vmx.lifecycle.exceptions import StatusTransitionError
from vmx.lifecycle.transition_validator import is_legal, require
from tests.conformance.fixtures.loader import load


@pytest.mark.conformance("LIFE-005")
def test_LIFE_005_construct_from_disposed_raises():
    with pytest.raises(StatusTransitionError) as exc_info:
        require(ConstructionStatus.DISPOSED, "construct")
    assert "Disposed" in str(exc_info.value)
    assert "construct" in str(exc_info.value)


@pytest.mark.conformance("LIFE-006")
def test_LIFE_006_destruct_from_disposed_raises():
    with pytest.raises(StatusTransitionError) as exc_info:
        require(ConstructionStatus.DISPOSED, "destruct")
    assert "Disposed" in str(exc_info.value)
    assert "destruct" in str(exc_info.value)


@pytest.mark.conformance("LIFE-011")
def test_LIFE_011_validator_matches_fixture_table():
    fixture = load("lifecycle-transitions.json")
    for row in fixture["transitions"]:
        frm = ConstructionStatus[row["from"].upper()]
        op = row["via"]
        expected_legal = row["legal"]
        assert is_legal(frm, op) == expected_legal, f"row {row}"


# LIFE-001..004, LIFE-007..010, LIFE-012, LIFE-013 require an actual VM instance.
# They live in test_component_vm.py / test_composite_vm.py and are duplicated
# here as delegations so the catalog coverage tool sees each ID present.

@pytest.mark.conformance("LIFE-001")
def test_LIFE_001_delegated():
    pytest.importorskip("vmx.components.component_vm")
    from tests.conformance.test_component_vm import test_CVM_001_construct_emits_status_messages
    test_CVM_001_construct_emits_status_messages()

# ... similarly for LIFE-002, 003, 004, 007, 008, 009, 010, 012, 013
```

(Use `pytest.importorskip` or direct delegation. The pattern allows the conformance tool to find the `@pytest.mark.conformance("LIFE-N")` marks even before the dependent test files exist.)

### Bundle fixture into package + verify

Update `pyproject.toml` (under `[tool.hatch.build.targets.wheel]`):

```toml
[tool.hatch.build.targets.wheel.force-include]
"../../spec/fixtures/lifecycle-transitions.json" = "vmx/lifecycle/_data/lifecycle-transitions.json"
"../../spec/fixtures/message-ordering.json" = "vmx/services/_data/message-ordering.json"
"../../spec/fixtures/command-truthtable.json" = "vmx/commands/_data/command-truthtable.json"
```

The validator loads via `importlib.resources` as shown above.

### Verify + commit

```bash
uv sync --all-extras
uv run pytest tests/unit/lifecycle/ tests/conformance/test_lifecycle.py -v 2>&1 | tail -15
uv run mypy --strict src/vmx/lifecycle 2>&1 | tail -5
uv run ruff check src/vmx/lifecycle tests/unit/lifecycle tests/conformance/test_lifecycle.py
```

Expected: lifecycle unit tests + LIFE-005, LIFE-006, LIFE-011 conformance pass; the delegated LIFE-001..004/007..010/012/013 fail with `ModuleNotFoundError` or `ImportError` (expected — they're for later tasks).

Commit message:

```
feat(python): Lifecycle module (3a) — ConstructionStatus, StatusTransitionError, transition validator

- lifecycle/status.py: 5-state IntEnum (DISPOSED=0, ..., CONSTRUCTED=4)
- lifecycle/exceptions.py: StatusTransitionError carries current_status + attempted_operation
- lifecycle/transition_validator.py: loads spec/fixtures/lifecycle-transitions.json
  bundled into the wheel via hatch force-include; same data source as the JSON
  test fixture, so LIFE-011 is trivially satisfied.
- Unit tests for the enum, the exception, and the validator.
- Conformance LIFE-005, LIFE-006, LIFE-011 implemented directly here;
  LIFE-001..004, 007..010, 012, 013 delegated to later tasks.

Refs: spec/02-lifecycle.md
```

______________________________________________________________________

## Task 3 — Messages (3b/1): Protocol hierarchy + concrete dataclasses + PROP-001..004 delegations

**Spec:** `spec/03-messages.md`.

### Files

- `langs/python/src/vmx/messages/__init__.py` — re-export everything.
- `langs/python/src/vmx/messages/protocols.py` — KEEP existing `Message`, `TypedMessage[TSender]`. Add `PropertyChangedMessageProto[TSender]` (Protocol with `property_name: str`) and `ConstructionStatusChangedMessageProto` (Protocol with `status: ConstructionStatus`).
- `langs/python/src/vmx/messages/property_changed.py` — `PropertyChangedMessage[TSender]` `@dataclass(frozen=True, slots=True)`. Fields: `sender: TSender`, `sender_name: str`, `property_name: str`. Properties: `sender_object` returns `sender`. Static `create(sender, sender_name, property_name)` factory.
- `langs/python/src/vmx/messages/construction_status.py` — `ConstructionStatusChangedMessage` similarly. Fields: `sender: object`, `sender_name: str`, `status: ConstructionStatus`.

Use `dataclass(frozen=True)` for value equality (dataclasses auto-generate `__eq__` and `__hash__` when frozen).

### Unit tests

`tests/unit/messages/test_messages.py` — verify:

- `PropertyChangedMessage.create(sender, name, prop)` returns instance with correct fields
- Two `PropertyChangedMessage`s with same values compare equal (dataclass eq)
- `ConstructionStatusChangedMessage.create(...)` similarly
- `sender_object` returns `sender`

### Conformance

`tests/conformance/test_property_change.py` — 4 PROP-\* tests that DELEGATE to `tests.conformance.test_component_vm`. Pattern:

```python
@pytest.mark.conformance("PROP-001")
def test_PROP_001_setter_different_value_publishes():
    pytest.importorskip("vmx.components.component_vm")
    from tests.conformance.test_component_vm import test_CVM_002_modeled_component_fires_property_changed_on_set
    test_CVM_002_modeled_component_fires_property_changed_on_set()
```

(PROP-001 maps to CVM-002 conceptually — same scenario, different prefix.)

### Commit message

```
feat(python): Messages module (3b/1) — PropertyChangedMessage, ConstructionStatusChangedMessage

- messages/property_changed.py: frozen dataclass PropertyChangedMessage[TSender]
  with sender, sender_name, property_name fields; sender_object property;
  create() classmethod factory.
- messages/construction_status.py: ConstructionStatusChangedMessage similarly
  carrying a ConstructionStatus.
- messages/protocols.py: kept existing Message + TypedMessage Protocols;
  added PropertyChangedMessageProto and ConstructionStatusChangedMessageProto
  for structural typing.
- Unit tests verify field initialization, value equality, sender_object getter.
- Conformance PROP-001..004 delegated to test_component_vm (Task 6).

Refs: spec/03-messages.md
```

______________________________________________________________________

## Task 4 — Services (3b/2): MessageHub + Dispatcher + RxDispatcher + HUB-001..007

**Spec:** `spec/03-messages.md` (hub), `spec/11-threading.md` (dispatcher), `spec/fixtures/message-ordering.json`.

### Files

- `langs/python/src/vmx/services/__init__.py` — re-export.
- `langs/python/src/vmx/services/message_hub.py` — extend with concrete `MessageHub` class.

```python
from __future__ import annotations

from typing import Generic, Protocol, TypeVar, runtime_checkable

import reactivex as rx
from reactivex.subject import Subject

from vmx.messages.protocols import Message

TMessage = TypeVar("TMessage", bound=Message, contravariant=True)


@runtime_checkable
class MessageHubProto(Protocol[TMessage]):
    """Hot pub/sub stream for IMessage events."""

    @property
    def messages(self) -> rx.Observable[Message]:
        ...

    def send(self, message: TMessage) -> None:
        ...


class MessageHub(Generic[TMessage]):
    """Default Subject-backed hub. Hot stream.
    
    Subscriber handlers that raise are isolated per-subscription so a bad
    handler doesn't terminate the stream (HUB-007).
    """

    def __init__(self) -> None:
        self._subject: Subject[Message] = Subject()
        self._disposed = False

    @property
    def messages(self) -> rx.Observable[Message]:
        # Wrap each subscription so handler exceptions are isolated.
        return rx.create(self._subscribe_safely)

    def _subscribe_safely(self, observer, scheduler=None):
        def on_next(value):
            try:
                observer.on_next(value)
            except Exception:
                pass  # swallow per spec/03-messages.md §Subscriber resilience
        return self._subject.subscribe(
            on_next=on_next,
            on_error=observer.on_error,
            on_completed=observer.on_completed,
        )

    def send(self, message: TMessage) -> None:
        if self._disposed:
            return
        self._subject.on_next(message)

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._subject.on_completed()
        self._subject.dispose()
```

- `langs/python/src/vmx/services/dispatcher.py` — Protocol + concrete:

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

import reactivex as rx
from reactivex.scheduler import ImmediateScheduler, ThreadPoolScheduler
from reactivex.scheduler.eventloop import AsyncIOScheduler


@runtime_checkable
class Dispatcher(Protocol):
    @property
    def foreground(self) -> rx.scheduler.SchedulerBase: ...
    @property
    def background(self) -> rx.scheduler.SchedulerBase: ...


class RxDispatcher:
    """Default Dispatcher. Caller injects schedulers explicitly."""

    def __init__(self, foreground: rx.scheduler.SchedulerBase, background: rx.scheduler.SchedulerBase) -> None:
        self._foreground = foreground
        self._background = background

    @property
    def foreground(self) -> rx.scheduler.SchedulerBase:
        return self._foreground

    @property
    def background(self) -> rx.scheduler.SchedulerBase:
        return self._background

    @classmethod
    def immediate(cls) -> "RxDispatcher":
        """Dispatcher with ImmediateScheduler for both fg and bg.
        Useful in console/CLI tools and tests."""
        return cls(ImmediateScheduler(), ImmediateScheduler())

    @classmethod
    def asyncio(cls, loop=None) -> "RxDispatcher":
        """Dispatcher with AsyncIOScheduler(loop) foreground + ThreadPoolScheduler background."""
        return cls(
            foreground=AsyncIOScheduler(loop=loop) if loop else AsyncIOScheduler(),
            background=ThreadPoolScheduler(),
        )
```

### Unit tests + conformance

`tests/unit/services/test_message_hub.py` — same scenarios as the C# tests (4 tests covering Send delivers, late subscribers, FIFO, exception isolation).

`tests/unit/services/test_rx_dispatcher.py` — basic constructor tests.

`tests/conformance/test_hub.py` — HUB-001..007 directly (no delegations). HUB-006 loads `message-ordering.json` and exercises every scenario.

### Commit message

```
feat(python): Services module (3b/2) — MessageHub + RxDispatcher

- services/message_hub.py: Subject-backed hot stream. Subscriber-handler
  exceptions are isolated via per-subscription wrapping (HUB-007).
- services/dispatcher.py: Dispatcher Protocol + RxDispatcher with foreground
  and background schedulers. Convenience factories: immediate() for tests,
  asyncio(loop) for asyncio-based UIs.

Unit tests cover send/late-subscribe/FIFO/exception isolation. Conformance
HUB-001..007 all pass — HUB-006 is fixture-driven from
spec/fixtures/message-ordering.json.

Refs: spec/03-messages.md, spec/11-threading.md
```

______________________________________________________________________

## Task 5 — Commands (3c): Command Protocol + RelayCommand + CMD-001..007

**Spec:** `spec/04-commands.md`, `spec/fixtures/command-truthtable.json`.

### Files

- `langs/python/src/vmx/commands/__init__.py`
- `langs/python/src/vmx/commands/protocols.py` — `Command` and `ParameterizedCommand[T]` Protocols. Members: `can_execute(self, parameter=None) -> bool`, `execute(self, parameter=None) -> None`, `can_execute_changed: rx.Observable[None]` (or similar; Python doesn't have BCL ICommand so we expose an Observable).
- `langs/python/src/vmx/commands/relay_command.py` — `RelayCommand` and `RelayCommand_Of_T`. Each has:
  - Frozen-dataclass-based immutable builder (`builder()` classmethod returns empty)
  - `.task(callable)` (optional), `.predicate(callable)` (optional), `.triggers(observable)` (optional, additive)
  - `.build()` returns the command instance
- Builder setters use `dataclasses.replace(self, ...)` to return new instances (BLD-001).

### Critical Python idioms

- Use `from __future__ import annotations` everywhere.
- `Callable[[], None]` for task; `Callable[[], bool]` for predicate.
- `Callable[[T], None]` and `Callable[[T], bool]` for parameterized.
- Predicate-null → `can_execute` returns True.
- Task-null → `execute` is a no-op.
- Predicate that raises → treat as False.
- Triggers re-fire `can_execute_changed`.
- Execute is gated on CanExecute (matches CMD-007 `predicate-false` row).

### Tests + conformance

Same pattern as C# Task 5. CMD-007 is fixture-driven from `command-truthtable.json`.

### Commit message

```
feat(python): Commands module (3c) — RelayCommand + parameterized variant

- commands/protocols.py: Command + ParameterizedCommand[T] Protocols.
  Each exposes can_execute(), execute(), and can_execute_changed Observable.
- commands/relay_command.py: RelayCommand + RelayCommand_Of_T concrete classes
  built via frozen-dataclass immutable fluent builders.
- Predicate-null defaults to True; task-null defaults to no-op; predicate
  raising is treated as False; execute is GATED on can_execute (matches
  fixtures/command-truthtable.json row "predicate-false").

Conformance CMD-001..007 pass. CMD-007 fixture-driven.

Refs: spec/04-commands.md, spec/fixtures/command-truthtable.json
```

______________________________________________________________________

## Tasks 6–10: Components / Composites / Groups / Aggregates / Forwarding

These mirror C# Phase 2 Tasks 6–10. For each: implement the module per the spec, with Python idioms:

- `Protocol` interfaces (use `@runtime_checkable` where useful)
- `_PrivateBase` abstract classes (single underscore prefix marks "module-internal but importable for subclassing")
- snake_case members
- `@dataclass(frozen=True, slots=True)` for builders
- Use `asyncio` for `async def construct(...)` variants
- Type hints with `from __future__ import annotations`
- `mypy --strict` clean

Each task ends with a commit covering: source + unit tests + conformance tests. The C# library at `/Users/kaveh/repos/VMx/langs/csharp/` is the working reference — when in doubt about behavior, port it.

### Task 6 — Components (3d): ComponentVM, ComponentVMOf, ReadonlyComponentVMOf

Files in `langs/python/src/vmx/components/`:

- `protocols.py` — `ComponentVM` Protocol (baseline), `ComponentVMOf[M]` Protocol, `ReadonlyComponentVMOf[M]` Protocol, `ViewModelType` enum.
- `base.py` — `_ComponentVMBase` abstract (similar to C# ComponentVMBase). Manages status, hub publishing, lifecycle ops, built-in commands.
- `component_vm.py` — `ComponentVM` (non-modeled), `ComponentVMOf` (modeled with settable model).
- `readonly_component_vm.py` — `ReadonlyComponentVMOf[M]`.
- `builders.py` — immutable frozen-dataclass builders. Required fields: `name`, `services(hub, dispatcher)`.
- `tests/unit/components/` — unit tests
- `tests/conformance/test_component_vm.py` — CVM-001..006 + delegated LIFE-001..010, 012 + PROP-001..004 implementations

Each conformance test marked with `@pytest.mark.conformance("XXX-NNN")`.

Commit message: `feat(python): Components module (3d) — ComponentVM + ComponentVMOf + ReadonlyComponentVMOf`

### Task 7 — Composites (3e): CompositeVM, CompositeVMOf

Files in `langs/python/src/vmx/composites/`. Behaviour per spec/06-composite-vm.md. Conformance COMP-001..011 + LIFE-013 dispose cascade.

### Task 8 — Groups (3f): GroupVM

Per spec/07-group-vm.md. Conformance GRP-001..004.

### Task 9 — Aggregates (3g): AggregateVM1..AggregateVM5

Per spec/08-aggregate-vm.md. Five classes (could be in one file). Conformance AGG-001..005.

### Task 10 — Forwarding (3h): ForwardingComponentVM + ForwardingCompositeVM

Per spec/09-forwarding.md. Conformance FWD-001..003.

______________________________________________________________________

## Tasks 11, 12 — Cross-cutting tests

### Task 11 — Builder conformance (3-cross-cutting): BLD-001..004

`tests/conformance/test_builders.py` — 4 tests against a representative VM (`ComponentVMOf[str]`):

- BLD-001: setter returns new builder instance (`b1 is not b2`)
- BLD-002: missing required field → `BuilderValidationError("ServiceHub")` or similar
- BLD-003: repeated `build()` produces distinct-but-equivalent VMs
- BLD-004: defaults applied when not set

Commit: `test(python): Builders conformance (3-cross-cutting) — BLD-001..004`

### Task 12 — Threading conformance (3-cross-cutting): THR-001..004

`tests/conformance/test_threading.py` — 4 tests using `TestScheduler`:

- THR-001: PropertyChanged via foreground
- THR-002: Background construct dispatches on background
- THR-003: CollectionChanged via foreground
- THR-004: Subscriber via ObserveOn(scheduler)

Commit: `test(python): Threading conformance (3-cross-cutting) — THR-001..004`

______________________________________________________________________

## Task 13 — Skip: no companion DI package for Python in 1.0

Python's DI conventions are less standardized than .NET's. Constructor injection works directly with any DI container (or no container at all). Defer a `vmx-extensions-di` package to post-1.0.

Add a note to `langs/python/README.md` explaining this choice.

______________________________________________________________________

## Task 14 — Full conformance verification

```bash
cd /Users/kaveh/repos/VMx
uv --project langs/python run pytest tests/conformance/ -v 2>&1 | tail -15
uv --project langs/python run python tools/check-conformance-coverage.py
```

Expected: every conformance test passes; coverage reports `python: 68/68 covered`.

```bash
cd /Users/kaveh/repos/VMx/langs/python
uv run pytest -v 2>&1 | tail -5
uv run mypy --strict src/vmx
uv run ruff check src tests
uv run ruff format --check src tests
```

All must be clean.

______________________________________________________________________

## Task 15 — Docs (3j): docs/getting-started/python.md

Mirror the C# tutorial — but Python-idiomatic. ~250-300 lines. Cover:

1. Install (`uv add vmx` once published; or local install)
1. Wire up MessageHub + Dispatcher
1. Build a ComponentVMOf[UserModel]
1. Build a RelayCommand
1. Build a CompositeVM[TabVM]
1. Lifecycle and cleanup
1. Threading (asyncio integration)
1. Where to go next

______________________________________________________________________

## Task 16 — Examples (3k): hello_vmx (console) + tk_todo_app (tkinter)

- `examples/python/hello_vmx/` — minimal Python console example
- `examples/python/tk_todo_app/` — tkinter MVVM demo

Both `python -m hello_vmx` and `python -m tk_todo_app` should run (tk requires display; just verify it imports).

______________________________________________________________________

## Task 17 — Tag python-v1.0.0 + CHANGELOG + push

### Step 17.1: Final verification

Same as Phase 2 Task 17 — all tests, mypy, ruff, conformance coverage green.

### Step 17.2: Update version + CHANGELOG + matrix

- `langs/python/src/vmx/__about__.py`: `__version__ = "1.0.0"`, `__min_spec_version__ = "1.0.0"`
- `langs/python/CHANGELOG.md`: replace `[Unreleased]` with `[1.0.0] — 2026-XX-XX` entry listing modules and 68 conformance tests
- `langs/python/pyproject.toml`: ensure `name = "vmx"` and any version isn't hardcoded (uses dynamic version from __about__.py)
- `compatibility-matrix.md`: update python column to `1.0.0`

### Step 17.3: Commit + tag

```bash
cd /Users/kaveh/repos/VMx
git add langs/python/src/vmx/__about__.py langs/python/CHANGELOG.md compatibility-matrix.md
git commit -m "release(python): python-v1.0.0 — full implementation of spec-v1.0.0

68 of 68 conformance IDs pass against spec-v1.0.0. Python 3.10-3.13 supported.

See langs/python/CHANGELOG.md for the full feature list.

Refs: docs/superpowers/specs/2026-05-16-vmx-multilang-revival-design.md §12.3"

git log -1 --format='%B' | grep -i "co-authored" && echo "FAIL" || echo "OK"

git tag -a python-v1.0.0 -m "VMx Python v1.0.0

First stable release of the Python flavor of VMx. Implements spec-v1.0.0
with all 68 conformance IDs green. Supported Python: 3.10, 3.11, 3.12, 3.13.

See langs/python/CHANGELOG.md for details."

git push -u origin feat/phase-3-python-v1
git push origin python-v1.0.0
```

DO NOT merge to main yet — that's Phase 4 / final.

______________________________________________________________________

## Phase 3 — completion criteria

1. All 17 tasks committed.
1. `uv run pytest` green: ~150+ unit tests + 68 conformance tests pass.
1. `uv run mypy --strict src/vmx` clean.
1. `uv run ruff check src tests` clean.
1. `uv run ruff format --check src tests` clean.
1. `uv --project langs/python run python tools/check-conformance-coverage.py` reports `python: 68/68 covered`.
1. `pre-commit run --all-files` passes all 11 hooks.
1. `langs/python/src/vmx/__about__.py` version is `1.0.0`.
1. `examples/python/hello_vmx/` runs successfully.
1. `examples/python/tk_todo_app/` imports cleanly.
1. `docs/getting-started/python.md` exists and is non-trivial.
1. Tag `python-v1.0.0` exists locally and on origin.
1. NO commits contain `Co-Authored-By: Claude` or any AI-attribution trailer.

Once all 13 are true, Phase 3 is complete — proceed to Phase 4 (polish + cross-language audit + final merge).
