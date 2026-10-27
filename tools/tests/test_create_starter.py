"""Unit tests for tools/create-starter.py. None of them needs the network."""

import ast
import json
import re
import sys
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


def _run_blocks(workflow: str) -> list[str]:
    """Return the body of every ``run: |`` block in a workflow."""
    blocks: list[str] = []
    lines = workflow.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "run: |":
            continue
        indent = len(line) - len(line.lstrip())
        body: list[str] = []
        for following in lines[index + 1 :]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            body.append(following)
        blocks.append("\n".join(body))
    return blocks


def _job(workflow: str, name: str) -> str:
    body = workflow.split(f"\n  {name}:\n", 1)[1]
    return re.split(r"\n  [a-z][a-z-]*:\n", body, maxsplit=1)[0]


def test_starters_workflow_is_a_least_privilege_clean_room_that_gates_no_pr() -> None:
    workflow = (REPO_ROOT / ".github/workflows/starters.yml").read_text(encoding="utf-8")
    triggers = workflow.split("\non:\n", 1)[1].split("\nconcurrency:\n", 1)[0]

    assert "  schedule:\n" in triggers
    assert "  workflow_dispatch:\n" in triggers
    assert "pull_request" not in triggers
    assert "push:" not in triggers
    assert "\npermissions:\n  contents: read\n" in workflow
    assert "write" not in workflow
    assert workflow.count("persist-credentials: false") == 4
    assert workflow.count("package-manager-cache: false") == 2
    assert "    cache:" not in workflow and "cache-dependency-path" not in workflow
    assert "python3 tools/create-starter.py" in workflow
    assert "VMX_VERSION: ${{ inputs.vmx-version }}" in workflow
    runs = _run_blocks(workflow)
    assert len(runs) == 4
    for run in runs:
        assert 'target="$(mktemp -d)"' in run
        assert "${{" not in run, "inputs reach run blocks only through env"


@pytest.mark.parametrize(
    ("job", "runner", "flags"),
    [
        ("typescript-node", "ubuntu-latest", ["--channel typescript-node"]),
        ("python-console", "ubuntu-latest", ["--channel python-console"]),
        ("swift-package", "macos-15", ["--channel swift-package"]),
        ("react-vite", "ubuntu-latest", ["--channel react-vite", "--browser-deps"]),
    ],
)
def test_starters_workflow_runs_each_channel_with_a_timeout(
    job: str, runner: str, flags: list[str]
) -> None:
    workflow = (REPO_ROOT / ".github/workflows/starters.yml").read_text(encoding="utf-8")
    body = _job(workflow, job)

    assert re.search(r"timeout-minutes: \d+", body), job
    assert f"runs-on: {runner}" in body
    for flag in flags:
        assert flag in body, (job, flag)
    minutes = int(re.search(r"timeout-minutes: (\d+)", body).group(1))  # type: ignore[union-attr]
    seconds = int(re.search(r"--timeout (\d+)", body).group(1))  # type: ignore[union-attr]
    assert seconds < minutes * 60, "the generator deadline must fire before the job timeout"


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


# --------------------------------------------------------------------------
# All channels
# --------------------------------------------------------------------------

EXPECTED_TEMPLATES = {
    "typescript-node": {
        ".gitignore",
        "src/main.ts",
        "src/notes.ts",
        "test/smoke.test.ts",
        "tsconfig.json",
    },
    "python-console": {
        ".gitignore",
        "notes_app/__init__.py",
        "notes_app/__main__.py",
        "notes_app/notes.py",
        "tests/test_smoke.py",
    },
    "swift-package": {
        ".gitignore",
        "Sources/Notes/Notes.swift",
        "Sources/NotesApp/main.swift",
        "Sources/NotesSmoke/main.swift",
    },
    "react-vite": {
        ".gitignore",
        "e2e/browser-smoke.mjs",
        "index.html",
        "src/App.tsx",
        "src/main.tsx",
        "src/notes.ts",
        "tsconfig.json",
        "vite.config.ts",
    },
}
VERSIONS = {
    "typescript-node": ("3.30.0", None),
    "python-console": ("3.23.0", None),
    "swift-package": ("3.24.0", None),
    "react-vite": ("0.1.1", "3.30.0"),
}


def test_every_channel_has_an_allowlist_and_a_manifest() -> None:
    assert set(starter.CHANNELS) == set(EXPECTED_TEMPLATES)
    assert set(starter.TEMPLATE_FILES) == set(starter.CHANNELS)
    assert set(starter.MANIFEST_FILES) == set(starter.CHANNELS)


@pytest.mark.parametrize("channel", sorted(EXPECTED_TEMPLATES))
def test_each_template_holds_only_its_version_free_allowlist(channel: str) -> None:
    files = {path.as_posix() for path in starter.template_files(channel)}

    assert files == EXPECTED_TEMPLATES[channel]
    assert starter.MANIFEST_FILES[channel] not in files, "the manifest is rendered, not copied"
    assert "README.md" not in files, "the README is rendered after verification"
    root = starter.template_dir(channel)
    for relative in files:
        text = (root / relative).read_text(encoding="utf-8")
        for needle in ("file:", "link:", "--find-links", "--extra-index-url", ".package(path:"):
            assert needle not in text, f"{channel}/{relative} holds {needle!r}"
        # A three-part version; an IPv4 address such as 127.0.0.1 is not one.
        assert not re.search(r"(?<![\d.])\d+\.\d+\.\d+(?![\d.])", text), (
            f"{channel}/{relative} hard-codes a version"
        )


@pytest.mark.parametrize("channel", sorted(EXPECTED_TEMPLATES))
def test_write_template_renders_each_channel_without_a_readme(channel: str, tmp_path: Path) -> None:
    version, core = VERSIONS[channel]
    written = starter.write_template(channel, version, tmp_path, core_version=core)

    manifest = starter.MANIFEST_FILES[channel]
    assert {path.as_posix() for path in written} == EXPECTED_TEMPLATES[channel] | {manifest}
    assert version in (tmp_path / manifest).read_text(encoding="utf-8")
    assert not (tmp_path / "README.md").exists(), "README is written only after verification"


def test_write_template_requires_a_core_version_for_react(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="core version"):
        starter.write_template("react-vite", "0.1.1", tmp_path)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--channel", "python-console", "--core-version", "3.30.0"], "--core-version"),
        (["--channel", "swift-package", "--registry", "https://mirror.example/"], "--registry"),
        (["--channel", "python-console", "--registry", REGISTRY], "--registry"),
        (["--channel", "typescript-node", "--browser-deps"], "--browser-deps"),
        (["--channel", "react-vite", "--core-version", "^3.30.0"], "exact X.Y.Z"),
        (["--channel", "swift-package", "--version", "swift-v3.24.0"], "exact X.Y.Z"),
        (["--channel", "python-console", "--version", "3.23.0.post1"], "exact X.Y.Z"),
    ],
)
def test_main_rejects_channel_options_before_any_network_call(
    args: list[str],
    message: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(starter.shutil, "which", lambda name: pytest.fail(f"looked up {name}"))
    monkeypatch.setattr(
        starter.urllib.request, "urlopen", lambda *a, **k: pytest.fail("opened a URL")
    )

    assert starter.main([*args, "--target", str(tmp_path / "out")]) == 1
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("channel", ["python-console", "swift-package", "react-vite"])
def test_main_refuses_a_non_empty_target_for_every_channel(
    channel: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "stray.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(starter.shutil, "which", lambda name: pytest.fail(f"looked up {name}"))
    monkeypatch.setattr(starter.platform, "system", lambda: "Darwin")
    version, core = VERSIONS[channel]
    args = ["--channel", channel, "--version", version, "--target", str(tmp_path)]
    if core is not None:
        args += ["--core-version", core]

    assert starter.main(args) == 1
    assert "is not empty" in capsys.readouterr().err


@pytest.mark.parametrize("channel", ["python-console", "swift-package", "react-vite"])
def test_main_refuses_a_target_inside_the_checkout_for_every_channel(
    channel: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(starter.shutil, "which", lambda name: pytest.fail(f"looked up {name}"))
    monkeypatch.setattr(starter.platform, "system", lambda: "Darwin")
    version, core = VERSIONS[channel]
    args = ["--channel", channel, "--version", version]
    args += ["--target", str(REPO_ROOT / "starters" / channel / "out")]
    if core is not None:
        args += ["--core-version", core]

    assert starter.main(args) == 1
    assert "inside the VMx checkout" in capsys.readouterr().err


def test_swift_channel_refuses_a_platform_without_combine(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(starter.platform, "system", lambda: "Linux")
    monkeypatch.setattr(starter.shutil, "which", lambda name: pytest.fail(f"looked up {name}"))
    args = ["--channel", "swift-package", "--version", "3.24.0", "--target", str(tmp_path)]

    assert starter.main(args) == 1
    assert "needs macOS" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("channel", "guide"),
    [
        ("python-console", starter.PYTHON_GUIDE_URL),
        ("swift-package", starter.SWIFT_GUIDE_URL),
        ("react-vite", starter.REACT_GUIDE_URL),
        ("react-vite", starter.UPGRADE_GUIDE_URL),
    ],
)
def test_readme_guides_exist_in_the_repository(channel: str, guide: str) -> None:
    assert channel in starter.CHANNELS
    assert (REPO_ROOT / guide.split("/blob/main/", 1)[1]).is_file()


# --------------------------------------------------------------------------
# python-console
# --------------------------------------------------------------------------


def _wheel(name: str, version: str, **extra: object) -> dict[str, object]:
    url = f"https://files.pythonhosted.org/packages/aa/bb/{name}-{version}-py3-none-any.whl"
    return {
        "download_info": {"url": url, "archive_info": {"hashes": {"sha256": "0" * 64}}},
        "is_direct": False,
        "requested": name == "vmx",
        "metadata": {"name": name, "version": version},
        **extra,
    }


PIP_REPORT = {
    "version": "1",
    "install": [
        _wheel("vmx", "3.23.0"),
        _wheel("reactivex", "6.1.0"),
        _wheel("typing_extensions", "4.16.0"),
    ],
}


def test_requirements_pin_the_exact_version_from_pypi_only() -> None:
    text = starter.render_requirements("3.23.0")
    requirements = [line for line in text.splitlines() if not line.startswith("#")]

    assert requirements == ["vmx==3.23.0"]
    assert "https://pypi.org/simple" in text
    for needle in ("-e", "file:", "--find-links", "--extra-index-url", "../"):
        assert needle not in " ".join(requirements)
    with pytest.raises(ValueError, match=r"exact X\.Y\.Z"):
        starter.render_requirements(">=3.23")


def test_scan_pip_report_accepts_pypi_wheels() -> None:
    assert starter.scan_pip_report(PIP_REPORT) == []
    assert starter.pip_report_version(PIP_REPORT, "vmx") == "3.23.0"
    assert starter.pip_report_version(PIP_REPORT, "Typing-Extensions") == "4.16.0"
    assert starter.pip_report_version(PIP_REPORT, "rxpy") is None


def test_scan_pip_report_rejects_local_direct_vcs_and_foreign_installs() -> None:
    report = {
        "install": [
            _wheel(
                "vmx",
                "3.23.0",
                download_info={"url": "file:///repo/langs/python", "dir_info": {"editable": True}},
            ),
            _wheel("reactivex", "6.1.0", is_direct=True),
            _wheel(
                "typing_extensions", "4.16.0", download_info={"url": "https://mirror.example/t.whl"}
            ),
            _wheel(
                "other", "1.0.0", download_info={"url": "git+https://example/o", "vcs_info": {}}
            ),
        ]
    }

    issues = "\n".join(starter.scan_pip_report(report))

    assert "vmx: installed from a local directory" in issues
    assert "vmx: downloaded from 'file:///repo/langs/python'" in issues
    assert "reactivex: is a direct URL or path requirement" in issues
    assert "typing_extensions: downloaded from 'https://mirror.example/t.whl'" in issues
    assert "other: installed from version control" in issues
    assert starter.scan_pip_report({"install": []}) == [
        "pip install report has no installed distributions"
    ]


def test_python_lock_pins_every_distribution_with_its_hash() -> None:
    lock = starter.render_python_lock(PIP_REPORT, python_minor="3.12")

    assert "--require-hashes" in lock
    assert re.findall(r"^(\S+)==(\S+) \\$", lock, re.MULTILINE) == [
        ("reactivex", "6.1.0"),
        ("typing-extensions", "4.16.0"),
        ("vmx", "3.23.0"),
    ]
    assert lock.count(f"--hash=sha256:{'0' * 64}") == 3


def test_python_lock_and_readme_name_the_cpython_version_they_match() -> None:
    # A lock made on 3.11+ pins reactivex 6.1.0, which has no 3.10 wheel.
    note = "This lock matches CPython 3.12; on another version, regenerate it."
    lock = starter.render_python_lock(PIP_REPORT, python_minor="3.12")
    readme = starter.render_python_readme(
        "3.23.0",
        python_version="3.12.4",
        python_minor="3.12",
        pip_version="26.2.2",
        platform_name="Linux x86_64",
    )

    assert lock.splitlines()[0] == f"# {note}"
    assert note in " ".join(readme.split())
    for bad in ("3", "3.12.4", "py312", ""):
        with pytest.raises(ValueError, match=r"major\.minor"):
            starter.render_python_lock(PIP_REPORT, python_minor=bad)


def test_pip_show_version_reads_the_version_field() -> None:
    output = "Name: vmx\nVersion: 3.23.0\nSummary: x\n"

    assert starter.pip_show_version(output) == "3.23.0"
    assert starter.pip_show_version("WARNING: Package(s) not found: vmx\n") is None


def test_python_environment_drops_redirecting_variables() -> None:
    env = starter.python_environment(
        {
            "PATH": "/usr/bin",
            "HOME": "/home/me",
            "PYTHONPATH": "/repo/langs/python/src",
            "PIP_INDEX_URL": "https://mirror.example/simple",
            "PIP_FIND_LINKS": "/repo/dist",
            "UV_INDEX_URL": "https://mirror.example/simple",
            "VIRTUAL_ENV": "/repo/langs/python/.venv",
        }
    )

    assert env["PATH"] == "/usr/bin" and env["HOME"] == "/home/me"
    for name in ("PYTHONPATH", "PIP_INDEX_URL", "PIP_FIND_LINKS", "UV_INDEX_URL", "VIRTUAL_ENV"):
        assert name not in env
    assert env["PIP_CONFIG_FILE"] == starter.os.devnull
    assert env["PYTHONNOUSERSITE"] == "1"


def test_python_template_imports_only_vmx_and_the_standard_library() -> None:
    root = starter.template_dir("python-console")
    modules: set[str] = set()
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules.add(node.module.split(".")[0])

    third_party = modules - set(sys.stdlib_module_names) - {"notes_app"}
    assert third_party == {"vmx"}


def test_python_smoke_test_covers_the_representative_flow() -> None:
    smoke = (starter.template_dir("python-console") / "tests/test_smoke.py").read_text(
        encoding="utf-8"
    )

    for needle in (
        "app.start()",
        "rename_current(",
        "save_current.execute()",
        "assertRaises(NoteConflictError)",
        "app.dispose()",
        "ConstructionStatus.DISPOSED",
        "StatusTransitionError",
        'version("vmx")',
        "requirements.txt",
    ):
        assert needle in smoke, needle


def test_python_readme_names_the_verified_version() -> None:
    text = starter.render_python_readme(
        "3.23.0",
        python_version="3.12.4",
        python_minor="3.12",
        pip_version="26.2.2",
        platform_name="Linux x86_64",
    )

    assert "**3.23.0**" in text
    assert "CPython 3.12.4, pip 26.2.2 (Linux x86_64)" in text
    assert "requirements.lock" in text and "--require-hashes" in text
    assert starter.PYTHON_GUIDE_URL in text


# --------------------------------------------------------------------------
# swift-package
# --------------------------------------------------------------------------

REVISION = "36229cabfcc02734ce8378e9a6eaa64bb258491b"
RESOLVED = {
    "pins": [
        {
            "identity": "vmx",
            "kind": "remoteSourceControl",
            "location": starter.SWIFT_PACKAGE_URL,
            "state": {"revision": REVISION, "version": "3.24.0"},
        }
    ],
    "version": 2,
}


def test_swift_manifest_pins_the_exact_release_and_the_vmx_product() -> None:
    text = starter.render_swift_manifest("3.24.0")

    assert '.package(url: "https://github.com/thekaveh/VMx.git", exact: "3.24.0")' in text
    assert text.count('.product(name: "VMx", package: "vmx")') == 3
    assert "platforms: [.macOS(.v13)]" in text
    assert "path:" not in text and "branch:" not in text and "revision:" not in text
    assert 'executableTarget(name: "NotesSmoke"' in text
    with pytest.raises(ValueError, match="https://"):
        starter.render_swift_manifest("3.24.0", url="git@github.com:thekaveh/VMx.git")


def test_scan_package_resolved_accepts_the_exact_pin() -> None:
    assert starter.scan_package_resolved(RESOLVED, "3.24.0") == []
    assert starter.resolved_revision(RESOLVED) == REVISION


def test_scan_package_resolved_rejects_drift_local_and_foreign_pins() -> None:
    resolved = {
        "pins": [
            {
                "identity": "vmx",
                "kind": "remoteSourceControl",
                "location": "https://github.com/someone/VMx.git",
                "state": {"revision": REVISION, "version": "3.20.0"},
            },
            {"identity": "local", "kind": "fileSystem", "location": "/repo", "state": {}},
        ]
    }

    issues = "\n".join(starter.scan_package_resolved(resolved, "3.24.0"))

    assert "vmx: location 'https://github.com/someone/VMx.git'" in issues
    assert "vmx: resolved '3.20.0', expected 3.24.0" in issues
    assert "local: kind 'fileSystem' is not remoteSourceControl" in issues
    assert "local: has no resolved revision" in issues
    assert starter.scan_package_resolved({"pins": []}, "3.24.0") == [
        "Package.resolved has no 'vmx' pin"
    ]


def test_ls_remote_pairs_semantic_and_swift_tags_on_one_commit() -> None:
    output = "\n".join(
        [
            "43cda13bc503cd645fb2eea137bec171b44b9f00\trefs/tags/swift-v3.24.0",
            f"{REVISION}\trefs/tags/swift-v3.24.0^{{}}",
            "9084d452641a90220e7c0b7401d30e209b31fa1f\trefs/tags/v3.24.0",
            f"{REVISION}\trefs/tags/v3.24.0^{{}}",
            f"{'1' * 40}\trefs/tags/v3.1.0",
            f"{'2' * 40}\trefs/tags/swift-v3.20.0",
            f"{'3' * 40}\trefs/tags/v3.20.0",
            f"{'4' * 40}\trefs/tags/swift-v3.30.0",
        ]
    )

    tags = starter.parse_ls_remote(output)

    assert tags["v3.24.0"] == tags["swift-v3.24.0"] == REVISION
    # 3.20.0 tags name different commits; 3.30.0 has no semantic tag.
    assert starter.swift_release_versions(tags) == ["3.24.0"]


def test_show_dependencies_version_reads_the_vmx_node() -> None:
    tree = {
        "identity": "starter",
        "dependencies": [
            {"identity": "vmx", "url": starter.SWIFT_PACKAGE_URL, "version": "3.24.0"}
        ],
    }

    assert starter.show_dependencies_version(tree) == ("3.24.0", starter.SWIFT_PACKAGE_URL)
    assert starter.show_dependencies_version({"dependencies": []}) == (None, None)


def test_swift_template_imports_only_vmx_and_apple_frameworks() -> None:
    root = starter.template_dir("swift-package")
    modules: set[str] = set()
    for path in root.rglob("*.swift"):
        modules.update(re.findall(r"^import (\w+)$", path.read_text(encoding="utf-8"), re.M))

    assert modules == {"Combine", "Foundation", "Notes", "VMx"}


def test_swift_smoke_covers_the_flow_and_the_pin() -> None:
    smoke = (starter.template_dir("swift-package") / "Sources/NotesSmoke/main.swift").read_text(
        encoding="utf-8"
    )

    for needle in (
        "VMxVersion.current",
        '"Package.swift"',
        "try app.start()",
        "renameCurrent(",
        "executeAsync()",
        "catch is NoteConflictError",
        "app.saveCurrent.execute()",
        "app.dispose()",
        ".disposed",
        "catch is StatusTransitionError",
        "exit(1)",
    ):
        assert needle in smoke, needle


def test_swift_readme_names_the_verified_release() -> None:
    text = starter.render_swift_readme(
        "3.24.0", revision=REVISION, swift_version="Swift version 6.1", platform_name="Darwin arm64"
    )

    assert "**3.24.0**" in text and f"`{REVISION}`" in text and "`v3.24.0`" in text
    assert "swift run NotesSmoke" in text
    assert starter.SWIFT_GUIDE_URL in text


# --------------------------------------------------------------------------
# react-vite
# --------------------------------------------------------------------------


def test_react_package_json_pins_both_vmx_packages_exactly() -> None:
    text = starter.render_react_package_json("0.1.1", "3.30.0")
    manifest = json.loads(text)

    assert manifest["dependencies"] == {
        "@thekaveh/vmx": "3.30.0",
        "@thekaveh/vmx-react": "0.1.1",
        "react": "^19.0.0",
        "react-dom": "^19.0.0",
        "rxjs": "^7.8.0",
        "use-sync-external-store": "^1.6.0",
    }
    assert "workspaces" not in manifest and "overrides" not in manifest
    assert "file:" not in text and "link:" not in text
    assert manifest["scripts"]["build"] == "tsc -p tsconfig.json && vite build"
    assert manifest["scripts"]["test:browser"] == "node e2e/browser-smoke.mjs"
    assert "playwright" in manifest["devDependencies"]
    with pytest.raises(ValueError, match=r"exact X\.Y\.Z"):
        starter.render_react_package_json("0.1.1", "^3.30.0")


def test_react_deduplicates_react_and_every_adapter_peer() -> None:
    assert set(starter.REACT_DEDUPLICATED_PACKAGES) == {
        "@thekaveh/vmx",
        "@thekaveh/vmx-react",
        "react",
        "react-dom",
        "rxjs",
        "use-sync-external-store",
    }
    lock = _lock(
        **CLEAN,
        **{
            "node_modules/react": _entry("react", "19.3.1"),
            "node_modules/@thekaveh/vmx-react": _entry("@thekaveh/vmx-react", "0.1.1"),
            "node_modules/@thekaveh/vmx-react/node_modules/react": _entry("react", "18.3.1"),
            "node_modules/react-dom": _entry("react-dom", "19.3.1"),
        },
    )

    assert starter.count_copies(lock, "react") == [
        "node_modules/@thekaveh/vmx-react/node_modules/react",
        "node_modules/react",
    ]
    assert starter.count_copies(lock, "react-dom") == ["node_modules/react-dom"]


def test_install_script_packages_lists_skipped_scripts() -> None:
    lock = _lock(
        **CLEAN,
        **{"node_modules/fsevents": {**_entry("fsevents", "2.3.3"), "hasInstallScript": True}},
    )

    assert starter.install_script_packages(lock) == ["node_modules/fsevents"]
    assert starter.install_script_packages(_lock(**CLEAN)) == []


def test_react_template_imports_only_published_entry_points() -> None:
    root = starter.template_dir("react-vite")
    specifiers: set[str] = set()
    for pattern in ("*.ts", "*.tsx", "*.mjs"):
        for path in root.rglob(pattern):
            specifiers.update(re.findall(r'from "([^"]+)"', path.read_text(encoding="utf-8")))

    external = {spec for spec in specifiers if not spec.startswith((".", "node:"))}
    assert external == {
        "@thekaveh/vmx",
        "@thekaveh/vmx-react",
        "@vitejs/plugin-react",
        "playwright",
        "react",
        "react-dom/client",
        "rxjs",
        "vite",
    }


def test_react_notes_model_matches_the_typescript_starter() -> None:
    react = (starter.template_dir("react-vite") / "src/notes.ts").read_text(encoding="utf-8")
    node = (starter.template_dir("typescript-node") / "src/notes.ts").read_text(encoding="utf-8")

    assert react == node


def test_react_app_uses_the_adapter_and_disposes_on_unmount() -> None:
    app = (starter.template_dir("react-vite") / "src/App.tsx").read_text(encoding="utf-8")
    main = (starter.template_dir("react-vite") / "src/main.tsx").read_text(encoding="utf-8")

    for needle in ("createVmxStore(app.hub)", "useVmx(", "useCommand(app.saveCurrent)"):
        assert needle in app, needle
    cleanup = app.split("return () => {", 1)[1].split("};", 1)[0]
    assert cleanup.index("store.dispose()") < cleanup.index("app.dispose()")
    assert "<StrictMode>" in main


def test_react_browser_smoke_covers_the_flow_and_console_errors() -> None:
    smoke = (starter.template_dir("react-vite") / "e2e/browser-smoke.mjs").read_text(
        encoding="utf-8"
    )

    for needle in (
        'manifest.dependencies["@thekaveh/vmx"]',
        "preview(",
        "chromium.launch()",
        'page.on("console"',
        'page.on("pageerror"',
        "Invalid hook call",
        '"constructed"',
        'title.fill("Groceries for Monday")',
        "save.click()",
        "another note already uses the title",
        "Close notebook",
        '"disposed"',
        "process.exitCode = failed ? 1 : 0",
    ):
        assert needle in smoke, needle


def test_react_readme_names_the_verified_stack() -> None:
    text = starter.render_react_readme(
        "0.1.1",
        "3.30.0",
        resolved={"react": "19.3.1", "vite": "8.3.5"},
        browser="chromium 156.0.8078.4",
        node_version="24.1.0",
        npm_version="11.0.0",
        platform_name="Linux x86_64",
    )

    assert "`@thekaveh/vmx-react` **0.1.1**" in text
    assert "`@thekaveh/vmx` **3.30.0**" in text
    assert "`react` 19.3.1, `vite` 8.3.5" in text
    assert "headless chromium 156.0.8078.4" in text
    assert "Invalid hook call" in text
    assert starter.REACT_GUIDE_URL in text and starter.UPGRADE_GUIDE_URL in text


# --------------------------------------------------------------------------
# Review hardening: interpreter location, git prompts, README tables
# --------------------------------------------------------------------------


def _fake_python(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    return path


def test_interpreter_refusal_accepts_an_interpreter_outside_the_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    python = _fake_python(tmp_path / "toolchain" / "bin" / "python3")

    starter.require_interpreter_outside_checkout(
        python, prefix=tmp_path / "toolchain", base_executable=python, repo_root=repo
    )


def test_interpreter_refusal_rejects_a_checkout_venv_interpreter(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base = _fake_python(tmp_path / "toolchain" / "bin" / "python3.10")
    venv = repo / "langs" / "python" / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(base)
    (venv / "pyvenv.cfg").write_text(f"home = {base.parent}\n", encoding="utf-8")

    # The path itself is in the checkout even though it resolves outside it.
    with pytest.raises(
        starter.StarterError, match=r"the interpreter .* is inside the VMx checkout"
    ):
        starter.require_interpreter_outside_checkout(
            venv / "bin" / "python", prefix=venv, base_executable=base, repo_root=repo
        )


@pytest.mark.parametrize("kind", ["symlink", "base", "home"])
def test_interpreter_refusal_follows_links_bases_and_venv_homes(kind: str, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    inside = _fake_python(repo / "toolchain" / "bin" / "python3")
    outside = tmp_path / "outside"
    (outside / "bin").mkdir(parents=True)
    executable = outside / "bin" / "python"
    base = None
    if kind == "symlink":
        executable.symlink_to(inside)
    else:
        _fake_python(executable)
    if kind == "base":
        base = inside
    if kind == "home":
        (outside / "pyvenv.cfg").write_text(f"home = {inside.parent}\n", encoding="utf-8")

    with pytest.raises(starter.StarterError, match="inside the VMx checkout"):
        starter.require_interpreter_outside_checkout(
            executable, prefix=outside, base_executable=base, repo_root=repo
        )


def test_venv_home_reads_pyvenv_cfg(tmp_path: Path) -> None:
    (tmp_path / "pyvenv.cfg").write_text(
        "include-system-site-packages = false\nhome = /opt/python/bin\nversion = 3.12.4\n",
        encoding="utf-8",
    )

    assert starter.venv_home(tmp_path) == Path("/opt/python/bin")
    assert starter.venv_home(tmp_path / "missing") is None


@pytest.mark.parametrize("kind", ["clean", "symlink", "home"])
def test_venv_check_rejects_a_starter_interpreter_that_resolves_into_the_checkout(
    kind: str, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    inside = _fake_python(repo / ".venv" / "bin" / "python3.10")
    outside = _fake_python(tmp_path / "toolchain" / "bin" / "python3.10")
    venv = tmp_path / "target" / ".venv"
    interpreter = starter.venv_python(venv)
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(inside if kind == "symlink" else outside)
    home = inside.parent if kind == "home" else outside.parent
    (venv / "pyvenv.cfg").write_text(f"home = {home}\n", encoding="utf-8")

    if kind == "clean":
        starter.require_venv_outside_checkout(venv, repo_root=repo)
    else:
        with pytest.raises(starter.StarterError, match="inside the VMx checkout"):
            starter.require_venv_outside_checkout(venv, repo_root=repo)


def test_main_refuses_a_checkout_interpreter_before_any_network_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout_python = REPO_ROOT / "langs" / "python" / ".venv" / "bin" / "python"
    monkeypatch.setattr(
        starter,
        "current_interpreter",
        lambda: (checkout_python, checkout_python.parents[1], Path("/usr/bin/python3")),
    )
    monkeypatch.setattr(starter.shutil, "which", lambda name: pytest.fail(f"looked up {name}"))
    monkeypatch.setattr(
        starter.urllib.request, "urlopen", lambda *a, **k: pytest.fail("opened a URL")
    )

    args = ["--channel", "python-console", "--target", str(tmp_path / "out")]
    assert starter.main(args) == 1
    assert "outside the checkout" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_git_environment_disables_credential_prompts() -> None:
    env = starter.git_environment({"PATH": "/usr/bin", "GIT_TERMINAL_PROMPT": "1"})

    assert env == {"PATH": "/usr/bin", "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}


def test_ls_remote_and_swiftpm_calls_use_the_no_prompt_environment() -> None:
    source = (REPO_ROOT / "tools" / "create-starter.py").read_text(encoding="utf-8")
    swift = source.split("def verify_swift_package(", 1)[1].split("\ndef ", 1)[0]
    ls_remote = source.split("def _ls_remote(", 1)[1].split("\ndef ", 1)[0]

    assert "env=git_environment()" in ls_remote
    assert "env = git_environment()" in swift
    assert swift.count("[swift, ") == swift.count("env=env") + 1  # `swift --version` only


@pytest.mark.parametrize(
    "readme",
    [
        starter.render_readme(
            "3.30.0", node_version="24.1.0", npm_version="11.0.0", platform_name="Linux"
        ),
        starter.render_python_readme(
            "3.23.0",
            python_version="3.12.4",
            python_minor="3.12",
            pip_version="26.2.2",
            platform_name="Linux",
        ),
        starter.render_swift_readme(
            "3.24.0", revision="0" * 40, swift_version="Swift version 6.1", platform_name="Darwin"
        ),
        starter.render_react_readme(
            "0.1.1",
            "3.30.0",
            resolved={"react": "19.3.1"},
            browser="chromium",
            node_version="24.1.0",
            npm_version="11.0.0",
            platform_name="Linux",
        ),
    ],
)
def test_generated_readme_tables_are_aligned(readme: str) -> None:
    table = [line for line in readme.splitlines() if line.startswith("| ")]

    assert table, "each README has a layout table"
    assert len({len(line) for line in table}) == 1, table
