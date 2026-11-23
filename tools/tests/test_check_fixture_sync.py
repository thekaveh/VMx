"""Unit tests for tools/check-fixture-sync.py."""

import subprocess
from pathlib import Path

import check_fixture_sync as cfs
import pytest

FIXTURE_NAMES = (
    "command-truthtable.json",
    "derived-properties.json",
    "lifecycle-transitions.json",
    "message-ordering.json",
)
COPY_DIRECTORIES = {
    "python-runtime": Path("langs/python/src/vmx/lifecycle/_data"),
    "python-tests": Path("langs/python/tests/conformance/fixtures/data"),
    "rust": Path("langs/rust/src/fixtures"),
    "swift": Path("langs/swift/Sources/VMx/Resources"),
}
NOT_COPIED = {
    "python-runtime": frozenset(
        {"command-truthtable.json", "derived-properties.json", "message-ordering.json"}
    ),
}
LABELS = tuple(COPY_DIRECTORIES)


def _expected_names(label: str) -> set[str]:
    return set(FIXTURE_NAMES) - NOT_COPIED.get(label, frozenset())


def _fixture_tree(root: Path) -> None:
    source = root / "spec" / "fixtures"
    source.mkdir(parents=True)
    for name in FIXTURE_NAMES:
        (source / name).write_text("{}\n", encoding="utf-8")
    for label, copy_dir in COPY_DIRECTORIES.items():
        (root / copy_dir).mkdir(parents=True)
        for name in sorted(_expected_names(label)):
            (root / copy_dir / name).write_text("{}\n", encoding="utf-8")


def _use(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(cfs, "repo_root", lambda: root)


def test_copy_directory_table_lists_the_four_flavor_copies() -> None:
    assert {label: Path(path) for label, path in cfs._COPY_DIRECTORIES.items()} == COPY_DIRECTORIES
    assert cfs._NOT_COPIED == NOT_COPIED


def test_main_reports_repository_lookup_timeout(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cfs,
        "repo_root",
        lambda: (_ for _ in ()).throw(subprocess.TimeoutExpired("git", 1)),
    )

    assert cfs.main() == 2
    assert "unable to locate repository root" in capsys.readouterr().err


def test_main_returns_zero_when_copies_match(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    _use(monkeypatch, tmp_path)

    assert cfs.main() == 0
    assert "matches" in capsys.readouterr().out


def test_main_fails_when_no_spec_fixtures_exist(tmp_path, monkeypatch, capsys) -> None:
    (tmp_path / "spec" / "fixtures").mkdir(parents=True)
    _use(monkeypatch, tmp_path)

    assert cfs.main() == 1
    assert "no fixtures found" in capsys.readouterr().err


@pytest.mark.parametrize("label", LABELS)
def test_main_returns_one_when_copy_drifts(label, tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    drifted = tmp_path / COPY_DIRECTORIES[label] / sorted(_expected_names(label))[0]
    drifted.write_text('{"drift": true}\n', encoding="utf-8")
    _use(monkeypatch, tmp_path)

    assert cfs.main() == 1
    err = capsys.readouterr().err
    assert f"{label} fixture copy drifted" in err
    assert str(drifted) in err


@pytest.mark.parametrize("label", LABELS)
def test_main_returns_one_when_copy_is_missing(label, tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    name = sorted(_expected_names(label))[0]
    (tmp_path / COPY_DIRECTORIES[label] / name).unlink()
    _use(monkeypatch, tmp_path)

    assert cfs.main() == 1
    err = capsys.readouterr().err
    assert f"missing {label} fixture copy: {COPY_DIRECTORIES[label] / name}" in err
    assert f"Re-sync: cp spec/fixtures/{name} {COPY_DIRECTORIES[label] / name}" in err


@pytest.mark.parametrize("label", LABELS)
def test_main_returns_one_when_copy_is_extra(label, tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    (tmp_path / COPY_DIRECTORIES[label] / "stale.json").write_text("{}\n", encoding="utf-8")
    _use(monkeypatch, tmp_path)

    assert cfs.main() == 1
    assert f"unexpected {label} fixture copy: {COPY_DIRECTORIES[label] / 'stale.json'}" in (
        capsys.readouterr().err
    )


def test_main_fails_when_spec_fixture_has_no_copy_in_any_directory(
    tmp_path, monkeypatch, capsys
) -> None:
    _fixture_tree(tmp_path)
    (tmp_path / "spec" / "fixtures" / "probe.json").write_text("{}\n", encoding="utf-8")
    _use(monkeypatch, tmp_path)

    assert cfs.main() == 1
    err = capsys.readouterr().err
    for label, copy_dir in COPY_DIRECTORIES.items():
        assert f"missing {label} fixture copy: {copy_dir / 'probe.json'}" in err


def test_fixture_outside_the_exemption_table_is_not_skipped(tmp_path, monkeypatch, capsys) -> None:
    # lifecycle-transitions.json is not exempt for python-runtime, so the runtime
    # directory must hold it; dropping it fails even though other fixtures are exempt.
    _fixture_tree(tmp_path)
    (tmp_path / COPY_DIRECTORIES["python-runtime"] / "lifecycle-transitions.json").unlink()
    _use(monkeypatch, tmp_path)

    assert cfs.main() == 1
    assert "missing python-runtime fixture copy" in capsys.readouterr().err


def test_exempt_fixture_copied_to_runtime_directory_fails(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    runtime = COPY_DIRECTORIES["python-runtime"]
    (tmp_path / runtime / "command-truthtable.json").write_text("{}\n", encoding="utf-8")
    _use(monkeypatch, tmp_path)

    assert cfs.main() == 1
    err = capsys.readouterr().err
    assert f"unexpected python-runtime fixture copy: {runtime / 'command-truthtable.json'}" in err


def test_exempt_fixture_is_not_required_in_its_directory(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    _use(monkeypatch, tmp_path)

    assert cfs.main() == 0
    err = capsys.readouterr().err
    assert "missing" not in err


def test_main_fails_when_exemption_names_no_spec_fixture(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    _use(monkeypatch, tmp_path)
    monkeypatch.setattr(cfs, "_NOT_COPIED", {"python-runtime": frozenset({"renamed-away.json"})})

    assert cfs.main() == 1
    assert "python-runtime fixture exemption names no spec fixture: renamed-away.json" in (
        capsys.readouterr().err
    )


def test_main_fails_when_exemption_names_no_copy_directory(tmp_path, monkeypatch, capsys) -> None:
    _fixture_tree(tmp_path)
    _use(monkeypatch, tmp_path)
    monkeypatch.setattr(cfs, "_NOT_COPIED", {"python-typo": frozenset({"message-ordering.json"})})

    assert cfs.main() == 1
    assert "fixture exemption names no copy directory: python-typo" in capsys.readouterr().err


def test_repository_copies_match_spec_fixtures() -> None:
    assert cfs.main() == 0
