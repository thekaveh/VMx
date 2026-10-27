"""Unit tests for tools/create-starter.py. None of them needs the network."""

import json
import re
from pathlib import Path

import create_starter as starter
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = starter.DEFAULT_REGISTRY


def _lock(**packages: dict[str, object]) -> dict[str, object]:
    root = {"name": "app", "dependencies": {"@thekaveh/vmx": "3.30.0", "rxjs": "^7.8.0"}}
    return {"lockfileVersion": 3, "packages": {"": root, **packages}}


def _entry(name: str, version: str) -> dict[str, object]:
    tarball = name.rsplit("/", 1)[-1]
    return {"version": version, "resolved": f"{REGISTRY}{name}/-/{tarball}-{version}.tgz"}


CLEAN = {
    "node_modules/@thekaveh/vmx": _entry("@thekaveh/vmx", "3.30.0"),
    "node_modules/rxjs": _entry("rxjs", "7.8.2"),
}


def test_validate_target_refuses_a_non_empty_directory(tmp_path: Path) -> None:
    (tmp_path / "stray.txt").write_text("x", encoding="utf-8")

    with pytest.raises(starter.StarterError, match="not empty"):
        starter.validate_target(tmp_path, repo_root=tmp_path / "repo")


def test_validate_target_refuses_paths_inside_the_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)

    for target in (repo, repo / "sub", repo / "missing" / "deeper", repo / "sub" / ".."):
        with pytest.raises(starter.StarterError, match="inside the VMx checkout"):
            starter.validate_target(target, repo_root=repo)


def test_validate_target_refuses_the_real_checkout_by_default() -> None:
    with pytest.raises(starter.StarterError, match="inside the VMx checkout"):
        starter.validate_target(REPO_ROOT / "starters" / "out")


def test_validate_target_refuses_a_file(tmp_path: Path) -> None:
    target = tmp_path / "file"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(starter.StarterError, match="not a directory"):
        starter.validate_target(target, repo_root=tmp_path / "repo")


def test_validate_target_accepts_empty_or_absent_directories(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    assert starter.validate_target(empty, repo_root=tmp_path / "repo") == empty.resolve()
    absent = tmp_path / "absent" / "child"
    assert starter.validate_target(absent, repo_root=tmp_path / "repo") == absent.resolve()


def test_main_rejects_a_non_empty_target_before_any_network_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "stray.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(starter.shutil, "which", lambda name: pytest.fail(f"looked up {name}"))

    assert starter.main(["--version", "3.30.0", "--target", str(tmp_path)]) == 1
    assert "is not empty" in capsys.readouterr().err


@pytest.mark.parametrize("version", ["^3.30.0", "3.30", "latest", "3.30.0-beta.1", "file:../vmx"])
def test_main_rejects_anything_but_an_exact_release_version(
    version: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert starter.main(["--version", version, "--target", str(tmp_path / "out")]) == 1
    assert "exact X.Y.Z" in capsys.readouterr().err


def test_package_json_pins_the_exact_version_with_no_local_references() -> None:
    text = starter.render_package_json("3.30.0")
    manifest = json.loads(text)

    assert manifest["dependencies"] == {"@thekaveh/vmx": "3.30.0", "rxjs": "^7.8.0"}
    assert manifest["type"] == "module"
    assert "workspaces" not in manifest
    assert "file:" not in text and "link:" not in text
    assert manifest["scripts"]["test"].endswith("node --test dist/test/smoke.test.js")
    assert manifest["scripts"]["start"].endswith("node dist/src/main.js")


def test_readme_names_the_verified_version_and_the_upgrade_guide() -> None:
    text = starter.render_readme(
        "3.30.0", node_version="24.1.0", npm_version="11.0.0", platform_name="Linux x86_64"
    )

    assert "**3.30.0**" in text
    assert "Node 24.1.0, npm 11.0.0" in text
    assert starter.UPGRADE_GUIDE_URL in text
    guide = starter.UPGRADE_GUIDE_URL.split("/blob/main/", 1)[1]
    assert (REPO_ROOT / guide).is_file()
    assert re.search(r"\{|\}", text.split("```bash", 1)[0]) is None


def test_template_holds_only_version_free_sources() -> None:
    files = {path.as_posix() for path in starter.template_files("typescript-node")}

    assert files == {
        ".gitignore",
        "src/main.ts",
        "src/notes.ts",
        "test/smoke.test.ts",
        "tsconfig.json",
    }
    root = starter.template_dir("typescript-node")
    for relative in files:
        text = (root / relative).read_text(encoding="utf-8")
        assert "file:" not in text and "link:" not in text, relative
        assert not re.search(r"\b3\.\d+\.\d+\b", text), f"{relative} hard-codes a version"


def test_template_imports_only_published_entry_points() -> None:
    root = starter.template_dir("typescript-node")
    specifiers: set[str] = set()
    for path in root.rglob("*.ts"):
        specifiers.update(re.findall(r'from "([^"]+)"', path.read_text(encoding="utf-8")))

    external = {spec for spec in specifiers if not spec.startswith((".", "node:"))}
    assert external == {"@thekaveh/vmx", "rxjs"}


def test_smoke_test_covers_the_representative_flow() -> None:
    smoke = (starter.template_dir("typescript-node") / "test/smoke.test.ts").read_text(
        encoding="utf-8"
    )

    for needle in (
        "app.start()",
        "renameCurrent(",
        "executeAsync()",
        "assert.rejects(",
        "saveCurrent.errors",
        "app.dispose()",
        "ConstructionStatus.Disposed",
        "StatusTransitionError",
        'manifest.dependencies["@thekaveh/vmx"]',
    ):
        assert needle in smoke, needle


def test_write_template_renders_into_an_empty_directory(tmp_path: Path) -> None:
    written = starter.write_template("typescript-node", "3.30.0", tmp_path)

    assert Path("package.json") in written
    assert json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))["dependencies"][
        "@thekaveh/vmx"
    ] == ("3.30.0")
    assert (tmp_path / "src" / "notes.ts").is_file()
    assert not (tmp_path / "README.md").exists(), "README is written only after verification"


def test_unknown_channel_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown starter channel"):
        starter.template_dir("swift-cli")


def test_scan_lockfile_accepts_registry_only_trees() -> None:
    assert starter.scan_lockfile(_lock(**CLEAN), REGISTRY) == []


def test_scan_lockfile_rejects_file_and_link_references() -> None:
    lock = _lock(
        **CLEAN,
        **{
            "node_modules/local-dep": {"resolved": "../local-dep", "link": True},
            "../local-dep": {"version": "1.0.0"},
            "node_modules/tarball": {"version": "1.0.0", "resolved": "file:../vmx-3.30.0.tgz"},
            "node_modules/spec": {"version": "file:../spec"},
        },
    )
    lock["packages"][""]["dependencies"]["local-dep"] = "file:../local-dep"  # type: ignore[index]

    issues = "\n".join(starter.scan_lockfile(lock, REGISTRY))

    assert "node_modules/local-dep: is a link" in issues
    assert "<root>: dependencies.local-dep uses 'file:../local-dep'" in issues
    assert "node_modules/tarball: resolved from 'file:../vmx-3.30.0.tgz'" in issues
    assert "node_modules/spec: version 'file:../spec' is a local reference" in issues
    assert "../local-dep: has no resolved registry URL" in issues


def test_scan_lockfile_rejects_a_foreign_registry_and_old_lockfiles() -> None:
    mirror = {"node_modules/rxjs": {"version": "7.8.2", "resolved": "https://mirror.example/rxjs"}}

    assert starter.scan_lockfile(_lock(**mirror), REGISTRY) == [
        f"node_modules/rxjs: resolved from 'https://mirror.example/rxjs', not {REGISTRY}"
    ]
    assert starter.scan_lockfile({"lockfileVersion": 1, "dependencies": {}}, REGISTRY) == [
        "package-lock.json has no lockfile v2/v3 'packages' map"
    ]


def test_count_copies_finds_nested_duplicate_peers() -> None:
    lock = _lock(
        **CLEAN,
        **{
            "node_modules/other": _entry("other", "1.0.0"),
            "node_modules/other/node_modules/rxjs": _entry("rxjs", "6.6.7"),
            "node_modules/rxjs-compat": _entry("rxjs-compat", "6.6.7"),
        },
    )

    assert starter.count_copies(lock, "rxjs") == [
        "node_modules/other/node_modules/rxjs",
        "node_modules/rxjs",
    ]
    assert starter.count_copies(lock, "@thekaveh/vmx") == ["node_modules/@thekaveh/vmx"]


def test_resolved_version_reads_npm_ls_json() -> None:
    listing = {"dependencies": {"@thekaveh/vmx": {"version": "3.30.0"}}}

    assert starter.resolved_version(listing, "@thekaveh/vmx") == "3.30.0"
    assert starter.resolved_version(listing, "rxjs") is None
    assert starter.resolved_version({}, "@thekaveh/vmx") is None


def test_starters_workflow_is_a_least_privilege_clean_room_that_gates_no_pr() -> None:
    workflow = (REPO_ROOT / ".github/workflows/starters.yml").read_text(encoding="utf-8")
    triggers = workflow.split("\non:\n", 1)[1].split("\nconcurrency:\n", 1)[0]

    assert "  schedule:\n" in triggers
    assert "  workflow_dispatch:\n" in triggers
    assert "pull_request" not in triggers
    assert "push:" not in triggers
    assert "\npermissions:\n  contents: read\n" in workflow
    assert "write" not in workflow
    assert "persist-credentials: false" in workflow
    assert "package-manager-cache: false" in workflow
    assert "    cache:" not in workflow and "cache-dependency-path" not in workflow
    assert 'target="$(mktemp -d)"' in workflow
    assert "python3 tools/create-starter.py" in workflow
    assert "VMX_VERSION: ${{ inputs.vmx-version }}" in workflow
    assert "${{ inputs." not in workflow.split("run: |", 1)[1]


def test_validate_target_refuses_a_differently_cased_path_to_the_checkout(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "Repo"
    repo.mkdir()
    alias = tmp_path / "REPO"
    if not alias.exists():
        pytest.skip("the file system is case-sensitive")

    with pytest.raises(starter.StarterError, match="inside the VMx checkout"):
        starter.validate_target(alias / "starter", repo_root=repo)


def test_template_files_reject_a_file_outside_the_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "typescript-node"
    for name in starter.TEMPLATE_FILES["typescript-node"]:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(starter, "STARTERS_ROOT", tmp_path)
    assert [path.as_posix() for path in starter.template_files("typescript-node")] == sorted(
        starter.TEMPLATE_FILES["typescript-node"]
    )

    (root / "package-lock.json").write_text("{}", encoding="utf-8")
    with pytest.raises(starter.StarterError, match=re.escape("package-lock.json")):
        starter.template_files("typescript-node")
