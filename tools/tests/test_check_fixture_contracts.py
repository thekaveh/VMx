"""Mutation tests for the canonical fixture inventory validator."""

import copy
import json
from pathlib import Path

import check_fixture_contracts as cfc
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _copy_fixtures(tmp_path: Path) -> Path:
    target = tmp_path / "fixtures"
    target.mkdir(parents=True)
    for name in (*cfc.EXPECTED_IDS, "lifecycle-transitions.json"):
        (target / name).write_bytes((ROOT / "spec" / "fixtures" / name).read_bytes())
    return target


def _mutate(path: Path, action) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    action(value)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_repository_fixtures_are_complete() -> None:
    assert cfc.main(["--fixtures", str(ROOT / "spec" / "fixtures")]) == 0


@pytest.mark.parametrize(
    ("name", "array"),
    [
        ("command-truthtable.json", "cases"),
        ("message-ordering.json", "scenarios"),
        ("derived-properties.json", "scenarios"),
        ("lifecycle-transitions.json", "transitions"),
    ],
)
def test_rejects_empty_and_partially_truncated_inventories(
    tmp_path: Path, name: str, array: str
) -> None:
    fixtures = _copy_fixtures(tmp_path)
    for retained in (0, 1):
        candidate = copy.deepcopy(json.loads((ROOT / "spec" / "fixtures" / name).read_text()))
        candidate[array] = candidate[array][:retained]
        (fixtures / name).write_text(json.dumps(candidate), encoding="utf-8")
        assert cfc.main(["--fixtures", str(fixtures)]) == 1


def test_rejects_duplicate_and_unsupported_schema(tmp_path: Path) -> None:
    fixtures = _copy_fixtures(tmp_path)
    command = fixtures / "command-truthtable.json"
    _mutate(command, lambda value: value["cases"].append(value["cases"][0]))
    assert cfc.main(["--fixtures", str(fixtures)]) == 1


def test_rejects_missing_required_field(tmp_path: Path) -> None:
    fixtures = _copy_fixtures(tmp_path)
    _mutate(
        fixtures / "command-truthtable.json",
        lambda value: value["cases"][0].pop("can_execute"),
    )
    assert cfc.main(["--fixtures", str(fixtures)]) == 1


@pytest.mark.parametrize(
    ("name", "mutation"),
    [
        (
            "lifecycle-transitions.json",
            lambda value: value.__setitem__("states", ["Banana"]),
        ),
        (
            "lifecycle-transitions.json",
            lambda value: value.__setitem__("initial_state", "Banana"),
        ),
        (
            "lifecycle-transitions.json",
            lambda value: value.__setitem__("terminal_states", []),
        ),
        (
            "lifecycle-transitions.json",
            lambda value: value["transitions"][0].__setitem__("legal", "yes"),
        ),
        (
            "command-truthtable.json",
            lambda value: value["cases"][0].__setitem__("predicate", "maybe"),
        ),
        (
            "command-truthtable.json",
            lambda value: value["cases"][0].__setitem__("can_execute", 17),
        ),
        (
            "derived-properties.json",
            lambda value: value["scenarios"][0].__setitem__("sources_initial", "not-an-array"),
        ),
        (
            "derived-properties.json",
            lambda value: value["scenarios"][1].__setitem__("mutations", [[9, 20]]),
        ),
        (
            "message-ordering.json",
            lambda value: value["scenarios"][0].__setitem__("producer_sends", "ABC"),
        ),
        (
            "message-ordering.json",
            lambda value: value["scenarios"][2].__setitem__("subscriber_count", 0),
        ),
    ],
)
def test_rejects_values_outside_fixture_domains(tmp_path: Path, name: str, mutation) -> None:
    fixtures = _copy_fixtures(tmp_path)
    _mutate(fixtures / name, mutation)

    assert cfc.main(["--fixtures", str(fixtures)]) == 1

    fixtures = _copy_fixtures(tmp_path / "schema")
    _mutate(
        fixtures / "message-ordering.json",
        lambda value: value.__setitem__("$schema-version", "2.0.0"),
    )
    assert cfc.main(["--fixtures", str(fixtures)]) == 1
