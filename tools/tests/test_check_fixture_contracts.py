"""Mutation tests for the canonical fixture schemas and inventory validator."""

import copy
import json
from pathlib import Path

import check_fixture_contracts as cfc
import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "spec" / "schemas" / "fixtures"
PUBLISHED_SCHEMAS = {
    "command-truthtable.json": "command-truthtable-v1.schema.json",
    "derived-properties.json": "derived-properties-v1.schema.json",
    "lifecycle-transitions.json": "lifecycle-transitions-v1.schema.json",
    "message-ordering.json": "message-ordering-v1.schema.json",
}


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


def _schema(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMAS / PUBLISHED_SCHEMAS[name]).read_text()))


def _fixture(name: str):
    return json.loads((ROOT / "spec" / "fixtures" / name).read_text(encoding="utf-8"))


def test_repository_fixtures_are_complete() -> None:
    assert cfc.main(["--fixtures", str(ROOT / "spec" / "fixtures")]) == 0


@pytest.mark.parametrize("name", sorted(PUBLISHED_SCHEMAS))
def test_each_fixture_has_a_valid_published_schema(name: str) -> None:
    Draft202012Validator.check_schema(
        json.loads((SCHEMAS / PUBLISHED_SCHEMAS[name]).read_text(encoding="utf-8"))
    )


@pytest.mark.parametrize("name", sorted(PUBLISHED_SCHEMAS))
def test_each_repository_fixture_validates_against_its_schema(name: str) -> None:
    errors = list(_schema(name).iter_errors(_fixture(name)))
    assert errors == []


@pytest.mark.parametrize(
    ("name", "mutation"),
    [
        (
            "lifecycle-transitions.json",
            lambda value: value["transitions"][7].__setitem__("to_final", "Disposed"),
        ),
        (
            "lifecycle-transitions.json",
            lambda value: value["transitions"][0].__setitem__("from", "Banana"),
        ),
        (
            "command-truthtable.json",
            lambda value: value["cases"][0].__setitem__("task", "stop"),
        ),
        (
            "command-truthtable.json",
            lambda value: value["cases"][0].__setitem__("extra", True),
        ),
        (
            "derived-properties.json",
            lambda value: value["scenarios"][4].pop("expected_emissions"),
        ),
        (
            "derived-properties.json",
            lambda value: value["scenarios"][0].__setitem__("sources_initial", []),
        ),
        (
            "derived-properties.json",
            lambda value: value["scenarios"][1].__setitem__("mutations", [[0, 20, 30]]),
        ),
        (
            "derived-properties.json",
            lambda value: value["transforms"].__setitem__("sum", 7),
        ),
        (
            "message-ordering.json",
            lambda value: value["scenarios"][0].__setitem__("unsubscribe_after_first", True),
        ),
        (
            "message-ordering.json",
            lambda value: value["scenarios"][1].__setitem__("description", "   "),
        ),
    ],
)
def test_published_schema_rejects_fixture_rules(name: str, mutation) -> None:
    candidate = copy.deepcopy(_fixture(name))
    mutation(candidate)

    assert list(_schema(name).iter_errors(candidate)) != []


def test_checker_reports_schema_violation_with_json_path(tmp_path: Path, capsys) -> None:
    fixtures = _copy_fixtures(tmp_path)
    _mutate(
        fixtures / "derived-properties.json",
        lambda value: value["scenarios"][4].pop("expected_emissions"),
    )

    assert cfc.main(["--fixtures", str(fixtures)]) == 1
    stderr = capsys.readouterr().err
    assert "derived-properties.json: $.scenarios[4]" in stderr
    assert "expected_emissions" in stderr


def test_checker_rejects_fixture_with_no_published_schema(tmp_path: Path, capsys) -> None:
    fixtures = _copy_fixtures(tmp_path)
    empty_schemas = tmp_path / "schemas"
    empty_schemas.mkdir()

    assert cfc.main(["--fixtures", str(fixtures), "--schemas", str(empty_schemas)]) == 1
    assert "no published schema" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("name", "mutation"),
    [
        (
            "derived-properties.json",
            lambda value: value["scenarios"][1].__setitem__("expected_values", [10]),
        ),
        (
            "derived-properties.json",
            lambda value: value["scenarios"][0].__setitem__("transform", "missing"),
        ),
        (
            "lifecycle-transitions.json",
            lambda value: value["transitions"].append(copy.deepcopy(value["transitions"][0])),
        ),
    ],
)
def test_checker_keeps_cross_field_and_inventory_rules(tmp_path: Path, name: str, mutation) -> None:
    fixtures = _copy_fixtures(tmp_path)
    _mutate(fixtures / name, mutation)

    assert cfc.main(["--fixtures", str(fixtures)]) == 1


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
            "derived-properties.json",
            lambda value: value["scenarios"][4].__setitem__("expected_emissions", "8,10"),
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


def test_rejects_fixture_with_no_contract_entry(tmp_path: Path, capsys) -> None:
    fixtures = _copy_fixtures(tmp_path)
    (fixtures / "probe.json").write_text("{}\n", encoding="utf-8")

    assert cfc.main(["--fixtures", str(fixtures)]) == 1
    assert "probe.json: no contract entry" in capsys.readouterr().err
