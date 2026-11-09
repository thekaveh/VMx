"""Contracts for the public-API baseline checks of every flavor (#1365)."""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import check_python_api as cpa
import check_rust_api_baseline as crab
import check_typescript_api as cta

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CSHARP_LIBRARIES = ("VMx", "VMx.Notifications", "VMx.Extensions.DependencyInjection")
SHA = re.compile(r"[0-9a-f]{40}")


def _job(workflow: str, name: str) -> str:
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", text
    )
    assert match is not None, f"{workflow} has no {name} job"
    return match.group("body")


# --- Python: introspection snapshot -------------------------------------------------


MAKE_WIDGET = "\ndef make_widget(size: int) -> Widget:\n    return Widget(size)\n"


def _toy_package(root: Path, extra: str = MAKE_WIDGET) -> str:
    name = f"toy_{uuid.uuid4().hex}"
    package = root / name
    (package / "impl").mkdir(parents=True)
    (package / "__init__.py").write_text(
        textwrap.dedent(
            f"""
            from __future__ import annotations
            import enum
            from {name}.impl.core import Widget, make_widget

            class Color(enum.Enum):
                RED = "red"

            LIMIT = 3
            __all__ = ["Color", "LIMIT", "Widget", "make_widget"]
            """
        ),
        encoding="utf-8",
    )
    (package / "impl" / "__init__.py").write_text("", encoding="utf-8")
    (package / "impl" / "core.py").write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            class _Base:
                def close(self) -> None: ...

            class Widget(_Base):
                size: int

                def __init__(self, size: int = 1) -> None:
                    self.size = size

                @property
                def area(self) -> int:
                    return self.size

                async def load(self, *, timeout: float = 1.0) -> None: ...

                @staticmethod
                def default() -> Widget:
                    return Widget()

                def _private(self) -> None: ...
            """
        )
        + extra,
        encoding="utf-8",
    )
    return name


def test_python_render_lists_exports_signatures_and_private_base_members(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.syspath_prepend(str(tmp_path))
    name = _toy_package(tmp_path)

    rendered = cpa.render_api(name)

    assert f"module {name}\n" in rendered
    assert "  class Color(Enum)\n    member RED = 'red'\n" in rendered
    assert "  LIMIT: int\n" in rendered
    assert "    property area [get] -> int\n" in rendered
    assert "    async def load(self, *, timeout: 'float' = 1.0) -> 'None'\n" in rendered
    assert "    static def default() -> 'Widget'\n" in rendered
    assert "    def close(self) -> 'None'\n" in rendered  # inherited from a private base
    assert "    attribute size: int\n" in rendered
    assert "_private" not in rendered
    assert "  def make_widget(size: 'int') -> 'Widget'\n" in rendered
    # The implementation module declares no __all__, so it is not a public module.
    assert "impl" not in rendered.replace(f"{name}.impl", "")


def test_python_main_fails_with_a_diff_when_a_member_is_removed(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(cpa, "PYTHON_VERSION", sys.version_info[:2])
    baseline = tmp_path / "api.txt"
    name = _toy_package(tmp_path)

    assert cpa.main(["--package", name, "--baseline", str(baseline), "--update"]) == 0
    assert cpa.main(["--package", name, "--baseline", str(baseline)]) == 0

    recorded = baseline.read_text(encoding="utf-8")
    baseline.write_text(recorded + "    def removed(self) -> 'None'\n", encoding="utf-8")
    capsys.readouterr()
    assert cpa.main(["--package", name, "--baseline", str(baseline)]) == 1
    captured = capsys.readouterr()
    assert "-    def removed(self) -> 'None'" in captured.out
    assert "major version bump" in captured.err


def test_python_main_refuses_an_unpinned_interpreter(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cpa, "PYTHON_VERSION", (2, 7))
    assert cpa.main([]) == 2
    assert "render the API on Python 2.7" in capsys.readouterr().err


def test_python_main_reports_a_missing_baseline(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(cpa, "PYTHON_VERSION", sys.version_info[:2])
    name = _toy_package(tmp_path)
    assert cpa.main(["--package", name, "--baseline", str(tmp_path / "none.txt")]) == 1
    assert "missing API baseline" in capsys.readouterr().err


def test_python_check_runs_on_the_pinned_interpreter_in_ci() -> None:
    workflow = (WORKFLOWS / "python.yml").read_text(encoding="utf-8")
    pinned = ".".join(map(str, cpa.PYTHON_VERSION))
    step = re.search(
        r"(?ms)- name: Compare the public API with the baseline\n(?P<body>.*?)(?=\n      - name:)",
        workflow,
    )
    assert step is not None
    assert f"matrix.python-version == '{pinned}'" in step.group("body")
    assert "../../tools/check-python-api.py" in step.group("body")
    assert "--update" not in step.group("body")
    assert (REPO_ROOT / "langs/python/api/vmx.api.txt").is_file()


# --- TypeScript: normalized declaration snapshot -------------------------------------


def _dist(root: Path, chunk_hash: str = "AbC-12_z", extra_export: str = "") -> Path:
    dist = root / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    for path in dist.iterdir():
        path.unlink()
    for suffix, module in ((".d.ts", ".js"), (".d.cts", ".cjs")):
        (dist / f"index{suffix}").write_text(
            f"import {{ A as Alpha }} from './shared-{chunk_hash}{module}';\n"
            f"export {{ Alpha{extra_export} }};\n",
            encoding="utf-8",
        )
        (dist / f"shared-{chunk_hash}{suffix}").write_text(
            "declare class A {\n    run(): void;   \n}\nexport { A };\n", encoding="utf-8"
        )
    return dist


def _package_json(root: Path) -> Path:
    path = root / "package.json"
    path.write_text(
        '{"exports": {".": {"import": {"types": "./dist/index.d.ts"}}}}', encoding="utf-8"
    )
    return path


def test_typescript_render_removes_chunk_hashes_and_trailing_spaces(tmp_path) -> None:
    rendered = cta.render_api(_dist(tmp_path), {"index"})

    assert "// ==== index.d.ts ====\nimport { A as Alpha } from './shared.js';\n" in rendered
    assert "// ==== shared.d.ts ====\ndeclare class A {\n    run(): void;\n}\n" in rendered
    assert "AbC-12_z" not in rendered
    # A rebuild that only changes the chunk hash renders the same snapshot.
    assert cta.render_api(_dist(tmp_path, chunk_hash="Zy9-8x7w"), {"index"}) == rendered


def test_typescript_main_fails_when_an_export_is_removed(tmp_path, capsys) -> None:
    package_json = _package_json(tmp_path)
    baseline = tmp_path / "api" / "vmx.api.txt"
    dist = _dist(tmp_path, extra_export=", Alpha as Beta")
    args = ["--dist", str(dist), "--package-json", str(package_json), "--baseline", str(baseline)]

    assert cta.main([*args, "--update"]) == 0
    assert cta.main(args) == 0

    _dist(tmp_path)
    capsys.readouterr()
    assert cta.main(args) == 1
    captured = capsys.readouterr()
    assert "-export { Alpha, Alpha as Beta };" in captured.out
    assert "major version bump" in captured.err


def test_typescript_rejects_diverging_commonjs_and_unknown_files(tmp_path, capsys) -> None:
    package_json = _package_json(tmp_path)
    dist = _dist(tmp_path)
    (dist / "index.d.cts").write_text("export {};\n", encoding="utf-8")
    assert cta.main(["--dist", str(dist), "--package-json", str(package_json)]) == 2
    assert "ESM and CommonJS declarations differ" in capsys.readouterr().err

    dist = _dist(tmp_path)
    (dist / "stray.d.ts").write_text("export {};\n", encoding="utf-8")
    assert cta.main(["--dist", str(dist), "--package-json", str(package_json)]) == 2
    assert "neither an entry point nor a hashed chunk" in capsys.readouterr().err


def test_typescript_render_ignores_comments(tmp_path) -> None:
    rendered = cta.render_api(_dist(tmp_path), {"index"})
    dist = tmp_path / "dist"
    for path in dist.glob("shared-*"):
        path.write_text(
            "/** Doc. */\ndeclare class A {\n    /**\n     * Runs `it`.\n     */\n"
            "    run(): void; // trailing\n    /* block */\n}\nexport { A };\n",
            encoding="utf-8",
        )
    assert cta.render_api(dist, {"index"}) == rendered


def test_typescript_comment_markers_inside_strings_stay() -> None:
    text = "type A = '/* x */' | \"// y\"; /** gone */\n\ntype B = `a//b`;\n"
    assert cta._strip_comments(text) == "type A = '/* x */' | \"// y\"; \n\ntype B = `a//b`;\n"


def test_typescript_entry_points_skip_exports_without_types(tmp_path) -> None:
    package_json = tmp_path / "package.json"
    package_json.write_text(
        '{"exports": {".": {"import": {"types": "./dist/index.d.ts"}},'
        ' "./package.json": "./package.json", "./raw": {"default": "./raw.js"}}}',
        encoding="utf-8",
    )
    assert cta.entry_points(package_json) == {"index"}


def test_typescript_entry_points_follow_the_exports_map() -> None:
    entries = cta.entry_points(REPO_ROOT / "langs/typescript/package.json")
    assert entries == {"index", "notifications", "conformance", "testing", "devtools"}
    snapshot = (REPO_ROOT / "langs/typescript/api/vmx.api.txt").read_text(encoding="utf-8")
    for entry in entries:
        assert f"// ==== {entry}.d.ts ====\n" in snapshot


def test_typescript_check_runs_after_the_build_in_ci() -> None:
    build = _job("typescript.yml", "build")
    build_at = build.index("run: npm run build\n")
    check_at = build.index("run: python3 ../../tools/check-typescript-api.py\n")
    assert build_at < check_at


# --- C#: PublicApiAnalyzers -----------------------------------------------------------


def test_csharp_libraries_track_public_api_files() -> None:
    props = (REPO_ROOT / "langs/csharp/Directory.Packages.props").read_text(encoding="utf-8")
    assert '<PackageVersion Include="Microsoft.CodeAnalysis.PublicApiAnalyzers"' in props
    for library in CSHARP_LIBRARIES:
        project = REPO_ROOT / "langs/csharp/src" / library
        csproj = (project / f"{library}.csproj").read_text(encoding="utf-8")
        assert (
            '<PackageReference Include="Microsoft.CodeAnalysis.PublicApiAnalyzers" '
            'PrivateAssets="all" />'
        ) in csproj
        shipped = (project / "PublicAPI.Shipped.txt").read_text(encoding="utf-8")
        unshipped = (project / "PublicAPI.Unshipped.txt").read_text(encoding="utf-8")
        assert shipped.startswith("#nullable enable\n")
        assert unshipped.startswith("#nullable enable\n")
        assert len(shipped.splitlines()) > 1
    # The baseline rules must fail the build; only the API-design rules are off.
    editorconfig = (REPO_ROOT / "langs/csharp/.editorconfig").read_text(encoding="utf-8")
    assert "dotnet_diagnostic.RS0016.severity" not in editorconfig
    assert "dotnet_diagnostic.RS0017.severity" not in editorconfig
    build_props = (REPO_ROOT / "langs/csharp/Directory.Build.props").read_text(encoding="utf-8")
    assert "<TreatWarningsAsErrors>true</TreatWarningsAsErrors>" in build_props


# --- Rust and Swift: recorded baseline revisions --------------------------------------


def test_rust_check_compares_with_the_recorded_revision() -> None:
    revision = (REPO_ROOT / "langs/rust/api/baseline-revision").read_text(encoding="utf-8")
    assert SHA.fullmatch(revision.strip())
    job = _job("rust.yml", "public-api")
    assert "fetch-depth: 0" in job
    assert "CSC_VERSION: 0.51.0" in job
    assert "sha256sum --check --strict" in job
    assert re.search(r"CSC_SHA256: [0-9a-f]{64}\n", job)
    assert "cargo semver-checks check-release" in job
    assert "langs/rust/api/baseline-revision" in job
    assert "public-api" in _job("rust.yml", "required")
    # The baseline must carry the pull request base's version, checked before the
    # comparison.
    guard = job.index('run: python3 tools/check-rust-api-baseline.py --base-rev "$BASE_SHA"')
    assert "BASE_SHA: ${{ github.event.pull_request.base.sha }}" in job
    assert guard < job.index("cargo semver-checks check-release")
    workflow = (WORKFLOWS / "rust.yml").read_text(encoding="utf-8")
    assert '- "tools/check-rust-api-baseline.py"' in workflow


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, timeout=60
    )
    return completed.stdout.strip()


def _commit_version(repo: Path, version: str) -> str:
    manifest = repo / "langs/rust/Cargo.toml"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(f'[package]\nname = "vmx-rs"\nversion = "{version}"\n', encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", version)
    return _git(repo, "rev-parse", "HEAD")


def _set_baseline(repo: Path, revision: str) -> None:
    path = repo / "langs/rust/api/baseline-revision"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(revision + "\n", encoding="utf-8")


def test_rust_baseline_must_carry_the_base_version(tmp_path, capsys) -> None:
    _git(tmp_path, "init", "-q")
    old = _commit_version(tmp_path, "0.36.0")
    _set_baseline(tmp_path, old)
    # A pull request that bumps the version compares with the old version.
    assert crab.main(["--root", str(tmp_path), "--base-rev", old]) == 0
    # After the bump merges, a pull request on top of it needs a new baseline.
    bumped = _commit_version(tmp_path, "0.37.0")
    capsys.readouterr()
    assert crab.main(["--root", str(tmp_path), "--base-rev", bumped]) == 1
    captured = capsys.readouterr()
    assert "declares vmx-rs 0.36.0" in captured.err
    assert f"for example {bumped}" in captured.err
    _set_baseline(tmp_path, bumped)
    assert crab.main(["--root", str(tmp_path), "--base-rev", bumped]) == 0
    assert crab.main(["--root", str(tmp_path), "--base-rev", "0" * 40]) == 2


def test_swift_check_compares_with_the_recorded_revision() -> None:
    revision = (REPO_ROOT / "langs/swift/api/baseline-revision").read_text(encoding="utf-8")
    assert SHA.fullmatch(revision.strip())
    assert (REPO_ROOT / "langs/swift/api/breakage-allowlist.txt").is_file()
    job = _job("swift.yml", "public-api")
    assert "fetch-depth: 0" in job
    assert "swift package diagnose-api-breaking-changes" in job
    assert "langs/swift/api/baseline-revision" in job
    assert "--breakage-allowlist-path langs/swift/api/breakage-allowlist.txt" in job
    assert "public-api" in _job("swift.yml", "required")


def test_contributing_documents_how_to_update_each_baseline() -> None:
    contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    section = contributing.split("### 2.8 Public API baselines", 1)[1].split("\n## ", 1)[0]
    for needle in (
        "PublicAPI.Unshipped.txt",
        "check-python-api.py --update",
        "check-typescript-api.py --update",
        "langs/rust/api/baseline-revision",
        "breakage-allowlist.txt",
        "major version bump",
        "minor bump while the version is 0.x",
        "check-rust-api-baseline.py",
        # An intended break recorded in an unreleased CHANGELOG section is
        # accepted by moving the Rust or Swift baseline revision forward.
        "the `develop` commit that merged the break",
    ):
        assert needle in section, needle
