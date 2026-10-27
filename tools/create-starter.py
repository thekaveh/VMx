#!/usr/bin/env python3
"""Generate a VMx application starter outside the checkout and verify it.

The generator copies the version-free template files from
``starters/<channel>/``, renders the version-bearing manifest, installs the
exact public package from its public registry, and checks the result. Each
channel checks:

* that the lockfile or install report has no local or path references and
  resolves every package from the public registry;
* that the resolved VMx version equals the pin;
* that the tree holds exactly one copy of each deduplicated peer (npm);
* that the starter's smoke test and entry point exit 0.

Channels: ``typescript-node`` (npm), ``python-console`` (PyPI),
``swift-package`` (SwiftPM, macOS) and ``react-vite`` (npm, with a headless
Chromium check of the built app).

It never publishes anything. The README is written last, after every check
passes, so its "verified" line is true.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Mapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STARTERS_ROOT = REPO_ROOT / "starters"
PACKAGE_NAME = "@thekaveh/vmx"
REACT_PACKAGE_NAME = "@thekaveh/vmx-react"
PYTHON_PACKAGE_NAME = "vmx"
DEFAULT_REGISTRY = "https://registry.npmjs.org/"
PYPI_INDEX_URL = "https://pypi.org/simple"
PYPI_JSON_URL = "https://pypi.org/pypi/vmx/json"
PYPI_FILES_URL = "https://files.pythonhosted.org/"
SWIFT_PACKAGE_URL = "https://github.com/thekaveh/VMx.git"
SWIFT_PACKAGE_IDENTITY = "vmx"
_DOCS_URL = "https://github.com/thekaveh/VMx/blob/main/docs/content/"
UPGRADE_GUIDE_URL = _DOCS_URL + "getting-started/upgrading-typescript.md"
PYTHON_GUIDE_URL = _DOCS_URL + "getting-started/python.md"
SWIFT_GUIDE_URL = _DOCS_URL + "getting-started/swift.md"
REACT_GUIDE_URL = _DOCS_URL + "integration/react.md"
# Packages that must resolve to one physical copy. VMx declares rxjs as a peer;
# a second copy splits Observable identity between VMx and the app.
DEDUPLICATED_PACKAGES = (PACKAGE_NAME, "rxjs")
# A second React copy breaks hooks ("Invalid hook call"); the 2026-08-10 React
# consumer pilots found it. The adapter's other peers must be single copies too.
REACT_DEDUPLICATED_PACKAGES = (
    PACKAGE_NAME,
    REACT_PACKAGE_NAME,
    "react",
    "react-dom",
    "rxjs",
    "use-sync-external-store",
)
NPM_CHANNELS = ("typescript-node", "react-vite")
CHANNELS = ("typescript-node", "python-console", "swift-package", "react-vite")
# The tracked template files per channel. Only these are copied, so build
# output, a virtual environment or a stale lockfile from a local run can never
# reach a starter.
TEMPLATE_FILES = {
    "typescript-node": (
        ".gitignore",
        "src/main.ts",
        "src/notes.ts",
        "test/smoke.test.ts",
        "tsconfig.json",
    ),
    "python-console": (
        ".gitignore",
        "notes_app/__init__.py",
        "notes_app/__main__.py",
        "notes_app/notes.py",
        "tests/test_smoke.py",
    ),
    "swift-package": (
        ".gitignore",
        "Sources/Notes/Notes.swift",
        "Sources/NotesApp/main.swift",
        "Sources/NotesSmoke/main.swift",
    ),
    "react-vite": (
        ".gitignore",
        "e2e/browser-smoke.mjs",
        "index.html",
        "src/App.tsx",
        "src/main.tsx",
        "src/notes.ts",
        "tsconfig.json",
        "vite.config.ts",
    ),
}
# The file each channel renders with the exact pin.
MANIFEST_FILES = {
    "typescript-node": "package.json",
    "python-console": "requirements.txt",
    "swift-package": "Package.swift",
    "react-vite": "package.json",
}
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_LOCAL_SPEC_RE = re.compile(r"^(?:file|link):")
_MINOR_RE = re.compile(r"^[0-9]+\.[0-9]+$")
_LS_REMOTE_RE = re.compile(r"^([0-9a-f]{40})\trefs/tags/(\S+)$")
# Environment variables that could point pip or Python at another index, a
# local directory or the checkout. The Python channel drops all of them.
_PYTHON_ENV_PREFIXES = ("PIP_", "PYTHON", "UV_", "VIRTUAL_ENV", "CONDA_")


class StarterError(RuntimeError):
    """A starter check failed."""


def require_version(version: str) -> None:
    """Reject anything except an exact X.Y.Z release version."""
    if _SEMVER_RE.fullmatch(version) is None:
        raise ValueError(f"expected an exact X.Y.Z release version, received {version!r}")


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def template_dir(channel: str) -> Path:
    """Return the tracked template directory for a channel."""
    if channel not in CHANNELS:
        raise ValueError(f"unknown starter channel {channel!r}; expected one of {CHANNELS}")
    return STARTERS_ROOT / channel


def template_files(channel: str) -> list[Path]:
    """Return the allowlisted template files, relative to the channel directory.

    Raise if a listed file is missing or if the directory holds any other file.
    """
    root = template_dir(channel)
    expected = {Path(name) for name in TEMPLATE_FILES[channel]}
    present = {path.relative_to(root) for path in root.rglob("*") if path.is_file()}
    missing = sorted(path.as_posix() for path in expected - present)
    extra = sorted(path.as_posix() for path in present - expected)
    if missing or extra:
        raise StarterError(
            f"template {root} does not match its allowlist: "
            f"missing {missing or 'nothing'}, unexpected {extra or 'nothing'}"
        )
    return sorted(expected)


def _is_inside(path: Path, root: Path) -> bool:
    """Report whether `path` or an existing ancestor is the same directory as `root`.

    The check compares file identity, not strings, so a case-insensitive file
    system cannot hide the checkout behind a differently cased path.
    """
    try:
        root_status = root.stat()
    except OSError:
        return False
    root_id = (root_status.st_dev, root_status.st_ino)
    for candidate in (path, *path.parents):
        try:
            status = candidate.stat()
        except OSError:
            continue
        if (status.st_dev, status.st_ino) == root_id:
            return True
    return False


def validate_target(target: Path, repo_root: Path = REPO_ROOT) -> Path:
    """Return the resolved target, or raise if it is unsafe to generate into.

    The target must lie outside the checkout and must be empty or absent, so
    no workspace, path dependency or stray file can leak into the starter.
    """
    resolved = target.expanduser().resolve()
    root = repo_root.resolve()
    if resolved == root or resolved.is_relative_to(root) or _is_inside(resolved, root):
        raise StarterError(f"target {resolved} is inside the VMx checkout {root}")
    if resolved.exists():
        if not resolved.is_dir():
            raise StarterError(f"target {resolved} exists and is not a directory")
        if any(resolved.iterdir()):
            raise StarterError(f"target {resolved} is not empty")
    return resolved


# --------------------------------------------------------------------------
# Rendering: TypeScript Node
# --------------------------------------------------------------------------


def render_package_json(version: str) -> str:
    """Render the TypeScript Node starter manifest with the exact VMx pin."""
    require_version(version)
    manifest = {
        "name": "vmx-starter-typescript-node",
        "version": "0.1.0",
        "private": True,
        "type": "module",
        "engines": {"node": ">=22"},
        "scripts": {
            "build": "tsc -p tsconfig.json",
            "start": "npm run build && node dist/src/main.js",
            "test": "npm run build && node --test dist/test/smoke.test.js",
        },
        "dependencies": {
            PACKAGE_NAME: version,
            "rxjs": "^7.8.0",
        },
        "devDependencies": {
            "@types/node": "^22.0.0",
            "typescript": "^6.0.3",
        },
    }
    return json.dumps(manifest, indent=2) + "\n"


def render_readme(version: str, *, node_version: str, npm_version: str, platform_name: str) -> str:
    """Render the TypeScript Node starter README that names the verified version."""
    require_version(version)
    return f"""# VMx TypeScript Node starter

A small Node application on `{PACKAGE_NAME}`. It builds a notebook of notes,
edits a note, saves it with a command, recovers from a store error and disposes
everything in order.

## Verified version

This starter was generated and verified with `{PACKAGE_NAME}` **{version}**
from the public npm registry on Node {node_version}, npm {npm_version}
({platform_name}).

## Prerequisites

- Node.js 22 or later. The VMx package itself supports Node 20.5 or later,
  but Node 20 is past its end of life.
- npm 10 or later.

## Commands

```bash
npm install   # already run by the generator
npm test      # compile, then run test/smoke.test.ts
npm start     # compile, then run src/main.ts
```

## Layout

| Path                  | Purpose                                                    |
| --------------------- | ---------------------------------------------------------- |
| `src/notes.ts`        | Note model, in-memory store, notebook VM and save command  |
| `src/main.ts`         | Runs the flow once and prints each step                    |
| `test/smoke.test.ts`  | Asserts construct, edit, command, error and dispose        |

## Dependencies

- `{PACKAGE_NAME}` is pinned to the exact version `{version}`.
- `rxjs` is a peer dependency of VMx. Keep one copy in the tree:
  `npm ls rxjs` must show a single version.
- Commit `package-lock.json` so every install resolves the same tree.

## Upgrading

1. Read the upgrade guide: {UPGRADE_GUIDE_URL}
1. Change the `{PACKAGE_NAME}` pin in `package.json` to the new exact version.
1. Run `npm install`, then `npm test`. The smoke test fails if the installed
   version differs from the pin.
"""


# --------------------------------------------------------------------------
# Rendering: Python console
# --------------------------------------------------------------------------


def render_requirements(version: str) -> str:
    """Render the Python starter requirements with the exact VMx pin."""
    require_version(version)
    return (
        "# The exact VMx release this starter runs on. Install it from PyPI:\n"
        "#   python -m pip install --index-url https://pypi.org/simple -r requirements.txt\n"
        f"{PYTHON_PACKAGE_NAME}=={version}\n"
    )


def report_distributions(report: Mapping[str, object]) -> list[tuple[str, str, str]]:
    """Return ``(name, version, sha256)`` for each distribution in a pip report."""
    entries: list[tuple[str, str, str]] = []
    for item in _report_items(report):
        metadata = item.get("metadata")
        download = item.get("download_info")
        if not isinstance(metadata, dict) or not isinstance(download, dict):
            raise StarterError("pip install report entry has no metadata or download_info")
        archive = download.get("archive_info")
        hashes = archive.get("hashes") if isinstance(archive, dict) else None
        digest = hashes.get("sha256") if isinstance(hashes, dict) else None
        name = metadata.get("name")
        version = metadata.get("version")
        if not (isinstance(name, str) and isinstance(version, str) and isinstance(digest, str)):
            raise StarterError(f"pip install report entry lacks a name, version or sha256: {item}")
        entries.append((_canonical_name(name), version, digest))
    return sorted(entries)


def _require_minor(python_minor: str) -> None:
    if _MINOR_RE.fullmatch(python_minor) is None:
        raise ValueError(f"expected a CPython major.minor such as 3.12, received {python_minor!r}")


def lock_python_note(python_minor: str) -> str:
    """Return the sentence that ties the lock to one CPython minor version."""
    _require_minor(python_minor)
    return f"This lock matches CPython {python_minor}; on another version, regenerate it."


def render_python_lock(report: Mapping[str, object], *, python_minor: str) -> str:
    """Render a hash-pinned lock from a ``pip install --report`` document.

    pip resolves for the running interpreter, so the lock holds only for that
    CPython minor version (for example, reactivex 6 needs 3.11 or later).
    """
    lines = [
        f"# {lock_python_note(python_minor)}",
        "# Generated from the starter's verified PyPI install. Reproduce the tree with:",
        "#   python -m pip install --index-url https://pypi.org/simple "
        "--require-hashes -r requirements.lock",
    ]
    lines.extend(
        f"{name}=={version} \\\n    --hash=sha256:{digest}"
        for name, version, digest in report_distributions(report)
    )
    return "\n".join(lines) + "\n"


def render_python_readme(
    version: str,
    *,
    python_version: str,
    python_minor: str,
    pip_version: str,
    platform_name: str,
) -> str:
    """Render the Python starter README that names the verified version."""
    require_version(version)
    lock_note = lock_python_note(python_minor)
    return f"""# VMx Python console starter

A small console application on the `{PYTHON_PACKAGE_NAME}` package. It builds a
notebook of notes, edits a note, saves it with a command, recovers from a store
error and disposes everything in order.

## Verified version

This starter was generated and verified with `{PYTHON_PACKAGE_NAME}` **{version}**
from PyPI on CPython {python_version}, pip {pip_version} ({platform_name}).

## Prerequisites

- CPython 3.10 or later.
- The commands below use the virtual environment in `.venv`, which the
  generator created and filled from PyPI.

## Commands

```bash
python3 -m venv .venv                       # already run by the generator
.venv/bin/python -m pip install --index-url https://pypi.org/simple -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v   # smoke test
.venv/bin/python -m notes_app                       # run the flow once
```

On Windows, use `.venv\\Scripts\\python.exe` instead of `.venv/bin/python`.

## Layout

| Path                    | Purpose                                                   |
| ----------------------- | --------------------------------------------------------- |
| `notes_app/notes.py`    | Note model, in-memory store, notebook VM and save command |
| `notes_app/__main__.py` | Runs the flow once and prints each step                   |
| `tests/test_smoke.py`   | Asserts construct, edit, command, error and dispose       |

## Dependencies

- `requirements.txt` pins `{PYTHON_PACKAGE_NAME}` to the exact version `{version}`.
- `requirements.lock` pins every installed distribution with its PyPI
  SHA-256 hash. Commit it, and install with `--require-hashes` to reproduce
  the verified tree. {lock_note}
- `reactivex` comes from VMx. The starter does not import it directly.

## Upgrading

1. Read the Python getting-started guide: {PYTHON_GUIDE_URL}
1. Change the `{PYTHON_PACKAGE_NAME}` pin in `requirements.txt` to the new exact version.
1. Reinstall, then run the smoke test. It fails if the installed version
   differs from the pin. Regenerate `requirements.lock` with the generator.
"""


# --------------------------------------------------------------------------
# Rendering: Swift package
# --------------------------------------------------------------------------


def render_swift_manifest(version: str, url: str = SWIFT_PACKAGE_URL) -> str:
    """Render the SwiftPM manifest pinned to one exact VMx release."""
    require_version(version)
    if not url.startswith("https://"):
        raise ValueError("SwiftPM package URL must use https://")
    swift_url = json.dumps(url)
    swift_version = json.dumps(version)
    vmx = f'.product(name: "VMx", package: "{SWIFT_PACKAGE_IDENTITY}")'
    return f"""// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "VMxStarter",
    platforms: [.macOS(.v13)],
    dependencies: [
        // SwiftPM resolves the semantic tag v{version}. The swift-v{version} tag
        // marks the same commit for the VMx release workflow.
        .package(url: {swift_url}, exact: {swift_version}),
    ],
    targets: [
        .target(name: "Notes", dependencies: [{vmx}]),
        .executableTarget(name: "NotesApp", dependencies: ["Notes", {vmx}]),
        // The smoke test is an executable, so it needs no XCTest or full Xcode.
        .executableTarget(name: "NotesSmoke", dependencies: ["Notes", {vmx}]),
    ]
)
"""


def render_swift_readme(
    version: str, *, revision: str, swift_version: str, platform_name: str
) -> str:
    """Render the Swift starter README that names the verified version."""
    require_version(version)
    return f"""# VMx Swift package starter

A small command-line package on the `VMx` SwiftPM product. It builds a notebook
of notes, edits a note, saves it with a command, recovers from a store error
and disposes everything in order.

## Verified version

This starter was generated and verified with VMx **{version}** from
<{SWIFT_PACKAGE_URL}>: tag `v{version}`, commit `{revision}`. The toolchain was
{swift_version} ({platform_name}).

## Prerequisites

- macOS 13 or later. VMx uses Combine, so the package does not build on Linux.
- A Swift 5.9 or later toolchain. The Command Line Tools are enough, because
  the smoke test is an executable and not an XCTest target.

## Commands

```bash
swift package resolve   # already run by the generator
swift run NotesSmoke    # smoke test: construct, edit, command, error, dispose
swift run NotesApp      # run the flow once
```

## Layout

| Path                            | Purpose                                                   |
| ------------------------------- | --------------------------------------------------------- |
| `Sources/Notes/Notes.swift`     | Note model, in-memory store, notebook VM and save command |
| `Sources/NotesApp/main.swift`   | Runs the flow once and prints each step                   |
| `Sources/NotesSmoke/main.swift` | Asserts construct, edit, command, error and dispose       |

## Dependencies

- `Package.swift` pins VMx with `exact: "{version}"`.
- `Package.resolved` records the resolved commit. Commit it so every checkout
  resolves the same revision.
- To add XCTest or Swift Testing targets, use a full Xcode toolchain.

## Upgrading

1. Read the Swift getting-started guide: {SWIFT_GUIDE_URL}
1. Change the `exact:` version in `Package.swift`.
1. Run `swift package update`, then `swift run NotesSmoke`. The smoke test
   fails if the resolved version differs from the pin.
"""


# --------------------------------------------------------------------------
# Rendering: React and Vite
# --------------------------------------------------------------------------


def render_react_package_json(version: str, core_version: str) -> str:
    """Render the React starter manifest with exact adapter and core pins."""
    require_version(version)
    require_version(core_version)
    manifest = {
        "name": "vmx-starter-react-vite",
        "version": "0.1.0",
        "private": True,
        "type": "module",
        "engines": {"node": ">=22.12"},
        "scripts": {
            "dev": "vite",
            "typecheck": "tsc -p tsconfig.json",
            "build": "tsc -p tsconfig.json && vite build",
            "preview": "vite preview",
            "test:browser": "node e2e/browser-smoke.mjs",
        },
        "dependencies": {
            PACKAGE_NAME: core_version,
            REACT_PACKAGE_NAME: version,
            "react": "^19.0.0",
            "react-dom": "^19.0.0",
            "rxjs": "^7.8.0",
            "use-sync-external-store": "^1.6.0",
        },
        "devDependencies": {
            "@types/react": "^19.0.0",
            "@types/react-dom": "^19.0.0",
            "@vitejs/plugin-react": "^6.0.0",
            "playwright": "^1.60.0",
            "typescript": "^6.0.3",
            "vite": "^8.0.0",
        },
    }
    return json.dumps(manifest, indent=2) + "\n"


def render_react_readme(
    version: str,
    core_version: str,
    *,
    resolved: Mapping[str, str],
    browser: str,
    node_version: str,
    npm_version: str,
    platform_name: str,
) -> str:
    """Render the React starter README that names the verified versions."""
    require_version(version)
    require_version(core_version)
    stack = ", ".join(f"`{name}` {resolved[name]}" for name in sorted(resolved))
    return f"""# VMx React and Vite starter

A small browser application on `{REACT_PACKAGE_NAME}` and `{PACKAGE_NAME}`. It
renders a notebook of notes. You can edit a note, save it with a command, see
a store error, and close the notebook, which disposes every view-model.

## Verified version

This starter was generated and verified with `{REACT_PACKAGE_NAME}` **{version}**
and `{PACKAGE_NAME}` **{core_version}** from the public npm registry on
Node {node_version}, npm {npm_version} ({platform_name}). The browser check ran
in headless {browser}.

Resolved stack: {stack}.

## Prerequisites

- Node.js 22.12 or later, which Vite 8 needs.
- npm 10 or later.
- For `npm run test:browser`, Playwright's Chromium:
  `npx playwright install --only-shell chromium`.

## Commands

```bash
npm install            # already run by the generator
npm run dev            # development server with StrictMode checks
npm run build          # type-check, then build dist/
npm run test:browser   # serve dist/ and drive it in headless Chromium
```

## Layout

| Path                    | Purpose                                                         |
| ----------------------- | --------------------------------------------------------------- |
| `src/notes.ts`          | Note model, in-memory store, notebook VM and save command       |
| `src/App.tsx`           | React UI on `createVmxStore`, `useVmx` and `useCommand`         |
| `src/main.tsx`          | Mounts the app under StrictMode                                 |
| `e2e/browser-smoke.mjs` | Asserts construct, edit, command, error, dispose, clean console |

## Dependencies

- `{REACT_PACKAGE_NAME}` and `{PACKAGE_NAME}` are pinned to exact versions.
- React, `rxjs` and `use-sync-external-store` are peer dependencies of the
  adapter. Keep one copy of each: `npm ls react rxjs` must show a single
  version. A second React copy fails with "Invalid hook call".
- Never link a VMx source directory into this app. Install published packages,
  or pack the source first.
- Commit `package-lock.json` so every install resolves the same tree.

## Upgrading

1. Read the React integration guide: {REACT_GUIDE_URL}
1. Read the upgrade guide: {UPGRADE_GUIDE_URL}
1. Change both exact pins in `package.json`. The adapter's peer range must
   include the new `{PACKAGE_NAME}` version.
1. Run `npm install`, `npm run build` and `npm run test:browser`.
"""


# --------------------------------------------------------------------------
# Process helpers
# --------------------------------------------------------------------------


def _which(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise StarterError(f"{name} is not on PATH")
    return path


def _remaining(deadline: float, maximum: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("starter generation exceeded its end-to-end timeout")
    return min(maximum, remaining)


def _run(
    args: list[str], *, cwd: Path, timeout: float, env: Mapping[str, str] | None = None
) -> str:
    """Run a command, echo its output, and return stdout."""
    print(f"$ {' '.join([Path(args[0]).name, *args[1:]])}", flush=True)
    result = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=None if env is None else dict(env),
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    if result.returncode != 0:
        raise StarterError(f"{' '.join(args)} exited {result.returncode}")
    return result.stdout


def _platform_name() -> str:
    return f"{platform.system()} {platform.machine()}"


# --------------------------------------------------------------------------
# npm checks (TypeScript Node and React)
# --------------------------------------------------------------------------


def latest_version(npm: str, registry: str, *, timeout: float, package: str = PACKAGE_NAME) -> str:
    """Return the version behind the registry's ``latest`` dist-tag."""
    result = subprocess.run(
        [npm, "view", package, "version", "--json", "--registry", registry],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise StarterError(f"npm view {package} failed: {result.stderr.strip()}")
    version = json.loads(result.stdout)
    if not isinstance(version, str):
        raise StarterError(f"npm view {package} returned {version!r}")
    require_version(version)
    return version


def scan_lockfile(lock: Mapping[str, object], registry: str = DEFAULT_REGISTRY) -> list[str]:
    """Return every local or foreign reference in an npm v2/v3 lockfile."""
    issues: list[str] = []
    packages = lock.get("packages")
    if not isinstance(packages, dict) or "" not in packages:
        return ["package-lock.json has no lockfile v2/v3 'packages' map"]
    for key, entry in packages.items():
        if not isinstance(entry, dict):
            issues.append(f"{key or '<root>'}: entry is not an object")
            continue
        label = key or "<root>"
        if entry.get("link") is True:
            issues.append(f"{label}: is a link to {entry.get('resolved')!r}")
        for field in ("dependencies", "devDependencies", "optionalDependencies"):
            specs = entry.get(field)
            if isinstance(specs, dict):
                issues.extend(
                    f"{label}: {field}.{name} uses {spec!r}"
                    for name, spec in specs.items()
                    if isinstance(spec, str) and _LOCAL_SPEC_RE.match(spec)
                )
        if key == "":
            continue
        resolved = entry.get("resolved")
        version = entry.get("version")
        if isinstance(version, str) and _LOCAL_SPEC_RE.match(version):
            issues.append(f"{label}: version {version!r} is a local reference")
        if not isinstance(resolved, str):
            if entry.get("link") is not True:
                issues.append(f"{label}: has no resolved registry URL")
        elif not resolved.startswith(registry):
            issues.append(f"{label}: resolved from {resolved!r}, not {registry}")
    return issues


def count_copies(lock: Mapping[str, object], name: str) -> list[str]:
    """Return every install location of a package in an npm v2/v3 lockfile."""
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        return []
    suffix = f"node_modules/{name}"
    return sorted(key for key in packages if key == suffix or key.endswith(f"/{suffix}"))


def install_script_packages(lock: Mapping[str, object]) -> list[str]:
    """Return the lockfile entries that declare an install script."""
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        return []
    return sorted(
        key
        for key, entry in packages.items()
        if key and isinstance(entry, dict) and entry.get("hasInstallScript") is True
    )


def resolved_version(npm_ls: Mapping[str, object], name: str) -> str | None:
    """Return the top-level resolved version from ``npm ls --json`` output."""
    dependencies = npm_ls.get("dependencies")
    if not isinstance(dependencies, dict):
        return None
    entry = dependencies.get(name)
    if not isinstance(entry, dict):
        return None
    version = entry.get("version")
    return version if isinstance(version, str) else None


def _npm_install_and_check(
    target: Path,
    *,
    npm: str,
    registry: str,
    deadline: float,
    pins: Mapping[str, str],
    deduplicated: tuple[str, ...],
) -> tuple[dict[str, object], dict[str, list[str]]]:
    """Install from the registry; check the lockfile, the pins and the copies."""
    _run(
        [npm, "install", "--registry", registry, "--ignore-scripts", "--no-audit", "--no-fund"],
        cwd=target,
        timeout=_remaining(deadline, 300),
    )
    lock = json.loads((target / "package-lock.json").read_text(encoding="utf-8"))
    issues = scan_lockfile(lock, registry)
    if issues:
        raise StarterError("lockfile is not clean-room:\n- " + "\n- ".join(issues))

    # `npm ls` exits non-zero on a missing or invalid peer, so it also checks
    # that every pinned version satisfies its dependents' peer ranges.
    listing = json.loads(_run([npm, "ls", "--json"], cwd=target, timeout=_remaining(deadline, 120)))
    for name, version in pins.items():
        installed = resolved_version(listing, name)
        if installed != version:
            raise StarterError(f"npm ls resolved {name}@{installed}, expected {version}")

    copies = {name: count_copies(lock, name) for name in deduplicated}
    duplicated = {name: paths for name, paths in copies.items() if len(paths) != 1}
    if duplicated:
        raise StarterError(f"expected exactly one copy of each peer, found {duplicated}")
    return listing, copies


def verify_typescript_node(
    target: Path, version: str, *, npm: str, registry: str, deadline: float
) -> dict[str, list[str]]:
    """Install the starter from the registry and run every clean-room check."""
    _, copies = _npm_install_and_check(
        target,
        npm=npm,
        registry=registry,
        deadline=deadline,
        pins={PACKAGE_NAME: version},
        deduplicated=DEDUPLICATED_PACKAGES,
    )
    _run([npm, "test"], cwd=target, timeout=_remaining(deadline, 300))
    _run([npm, "start"], cwd=target, timeout=_remaining(deadline, 120))
    return copies


def verify_react_vite(
    target: Path,
    version: str,
    core_version: str,
    *,
    npm: str,
    registry: str,
    deadline: float,
    browser_deps: bool = False,
) -> tuple[dict[str, str], dict[str, list[str]], str]:
    """Install, build and drive the React starter in headless Chromium.

    Return the resolved stack, the peer copies and the browser name.
    """
    listing, copies = _npm_install_and_check(
        target,
        npm=npm,
        registry=registry,
        deadline=deadline,
        pins={PACKAGE_NAME: core_version, REACT_PACKAGE_NAME: version},
        deduplicated=REACT_DEDUPLICATED_PACKAGES,
    )
    lock = json.loads((target / "package-lock.json").read_text(encoding="utf-8"))
    scripted = install_script_packages(lock)
    if scripted:
        # --ignore-scripts skipped these. The build and the browser check below
        # prove the starter does not need them.
        print("Skipped install scripts (--ignore-scripts): " + ", ".join(scripted))
    stack = {
        name: version_
        for name in (
            "react",
            "react-dom",
            "rxjs",
            "use-sync-external-store",
            "vite",
            "playwright",
        )
        if (version_ := resolved_version(listing, name)) is not None
    }

    _run([npm, "run", "build"], cwd=target, timeout=_remaining(deadline, 300))
    install = [npm, "exec", "--no", "--", "playwright", "install", "--only-shell"]
    if browser_deps:
        install.append("--with-deps")
    _run([*install, "chromium"], cwd=target, timeout=_remaining(deadline, 600))
    output = _run([npm, "run", "test:browser"], cwd=target, timeout=_remaining(deadline, 180))
    match = re.search(r"^browser: (.+)$", output, re.MULTILINE)
    browser = match.group(1).strip() if match else "Chromium"
    return stack, copies, browser


# --------------------------------------------------------------------------
# PyPI checks (Python console)
# --------------------------------------------------------------------------


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _report_items(report: Mapping[str, object]) -> list[dict[str, object]]:
    items = report.get("install")
    if not isinstance(items, list):
        raise StarterError("pip install report has no 'install' list")
    return [item for item in items if isinstance(item, dict)]


def scan_pip_report(report: Mapping[str, object], files_url: str = PYPI_FILES_URL) -> list[str]:
    """Return every non-PyPI, direct, local or editable install in a pip report."""
    items = report.get("install")
    if not isinstance(items, list) or not items:
        return ["pip install report has no installed distributions"]
    issues: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            issues.append("pip install report entry is not an object")
            continue
        metadata = item.get("metadata")
        name = metadata.get("name") if isinstance(metadata, dict) else None
        label = name if isinstance(name, str) else "<unnamed>"
        if item.get("is_direct") is True:
            issues.append(f"{label}: is a direct URL or path requirement")
        download = item.get("download_info")
        if not isinstance(download, dict):
            issues.append(f"{label}: has no download_info")
            continue
        if "dir_info" in download:
            issues.append(f"{label}: installed from a local directory")
        if "vcs_info" in download:
            issues.append(f"{label}: installed from version control")
        url = download.get("url")
        if not isinstance(url, str) or not url.startswith(files_url):
            issues.append(f"{label}: downloaded from {url!r}, not {files_url}")
    return issues


def pip_report_version(report: Mapping[str, object], name: str) -> str | None:
    """Return the version the pip report installed for a distribution."""
    wanted = _canonical_name(name)
    for item in _report_items(report):
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            continue
        candidate = metadata.get("name")
        version = metadata.get("version")
        if isinstance(candidate, str) and _canonical_name(candidate) == wanted:
            return version if isinstance(version, str) else None
    return None


def pip_show_version(output: str) -> str | None:
    """Return the ``Version:`` field of ``pip show`` output."""
    match = re.search(r"^Version: (\S+)$", output, re.MULTILINE)
    return match.group(1) if match else None


def latest_pypi_version(*, timeout: float, url: str = PYPI_JSON_URL) -> str:
    """Return the latest release of ``vmx`` from the PyPI JSON API."""
    with urllib.request.urlopen(url, timeout=timeout) as response:
        document = json.load(response)
    info = document.get("info") if isinstance(document, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    if not isinstance(version, str):
        raise StarterError(f"PyPI returned no version for {PYTHON_PACKAGE_NAME}")
    require_version(version)
    return version


def python_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an environment that cannot redirect pip or Python imports.

    It drops ``PIP_*``, ``PYTHON*``, ``UV_*``, virtual-environment and conda
    variables, and points pip at no configuration file, so neither a user
    ``pip.conf`` nor a ``PYTHONPATH`` into the checkout can leak in.
    """
    source = os.environ if base is None else base
    env = {key: value for key, value in source.items() if not key.startswith(_PYTHON_ENV_PREFIXES)}
    env["PIP_CONFIG_FILE"] = os.devnull
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def venv_python(venv: Path) -> Path:
    """Return the interpreter path inside a virtual environment."""
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def venv_home(prefix: Path) -> Path | None:
    """Return the ``home`` directory that a venv's ``pyvenv.cfg`` points to."""
    try:
        text = (prefix / "pyvenv.cfg").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "home" and value.strip():
            return Path(value.strip())
    return None


def _inside_checkout(path: Path, repo_root: Path) -> bool:
    root = repo_root.resolve()
    for candidate in (path.expanduser().absolute(), path.expanduser().resolve()):
        if candidate.is_relative_to(root) or _is_inside(candidate, root):
            return True
    return False


def require_interpreter_outside_checkout(
    executable: Path,
    *,
    prefix: Path | None = None,
    base_executable: Path | None = None,
    repo_root: Path = REPO_ROOT,
) -> None:
    """Refuse an interpreter that lives in, links into or is a venv of the checkout.

    ``python -m venv`` can link the new interpreter to the running one. An
    interpreter from a checkout venv, such as ``langs/python/.venv``, would
    then tie the starter to the checkout.
    """
    candidates = [("interpreter", executable)]
    if base_executable is not None:
        candidates.append(("base interpreter", base_executable))
    if prefix is not None:
        candidates.append(("interpreter prefix", prefix))
        home = venv_home(prefix)
        if home is not None:
            candidates.append(("venv home", home))
    for label, path in candidates:
        if _inside_checkout(path, repo_root):
            raise StarterError(
                f"the {label} {path} is inside the VMx checkout {repo_root.resolve()}; "
                "run the generator with a Python interpreter outside the checkout"
            )


def require_venv_outside_checkout(venv: Path, repo_root: Path = REPO_ROOT) -> None:
    """Refuse a starter venv whose interpreter or ``home`` resolves into the checkout."""
    interpreter = venv_python(venv)
    if _inside_checkout(interpreter, repo_root):
        raise StarterError(
            f"the starter interpreter {interpreter} resolves to {interpreter.resolve()}, "
            f"inside the VMx checkout {repo_root.resolve()}"
        )
    home = venv_home(venv)
    if home is not None and _inside_checkout(home, repo_root):
        raise StarterError(f"the starter venv home {home} is inside the VMx checkout")


def current_interpreter() -> tuple[Path, Path, Path]:
    """Return the running interpreter, its prefix and its base interpreter."""
    executable = Path(sys.executable)
    base = Path(getattr(sys, "_base_executable", sys.executable))
    return executable, Path(sys.prefix), base


def verify_python_console(
    target: Path, version: str, *, python: str, deadline: float
) -> dict[str, str]:
    """Create a venv in the target, install from PyPI and run every check."""
    env = python_environment()
    venv = target / ".venv"
    _run([python, "-m", "venv", str(venv)], cwd=target, timeout=_remaining(deadline, 120), env=env)
    require_venv_outside_checkout(venv)
    interpreter = str(venv_python(venv))
    python_version = _run(
        [interpreter, "-c", "import platform; print(platform.python_version())"],
        cwd=target,
        timeout=_remaining(deadline, 30),
        env=env,
    ).strip()
    python_minor = ".".join(python_version.split(".")[:2])
    pip = [interpreter, "-m", "pip"]
    index = ["--index-url", PYPI_INDEX_URL, "--no-cache-dir"]
    # A current pip writes a stable install report (format version 1).
    _run(
        [*pip, "install", *index, "--upgrade", "pip"],
        cwd=target,
        timeout=_remaining(deadline, 300),
        env=env,
    )
    with tempfile.TemporaryDirectory(prefix="vmx-starter-pip-") as scratch:
        report_path = Path(scratch) / "install-report.json"
        _run(
            [*pip, "install", *index, "--report", str(report_path), "-r", "requirements.txt"],
            cwd=target,
            timeout=_remaining(deadline, 300),
            env=env,
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
    issues = scan_pip_report(report)
    if issues:
        raise StarterError("pip install is not clean-room:\n- " + "\n- ".join(issues))
    reported = pip_report_version(report, PYTHON_PACKAGE_NAME)
    if reported != version:
        raise StarterError(f"pip installed {PYTHON_PACKAGE_NAME} {reported}, expected {version}")

    shown = pip_show_version(
        _run(
            [*pip, "show", PYTHON_PACKAGE_NAME],
            cwd=target,
            timeout=_remaining(deadline, 60),
            env=env,
        )
    )
    if shown != version:
        raise StarterError(f"pip show reports {PYTHON_PACKAGE_NAME} {shown}, expected {version}")

    # -I isolates the probe from the working directory and user site-packages.
    probe = json.loads(
        _run(
            [
                interpreter,
                "-I",
                "-c",
                "import json, vmx; print(json.dumps([vmx.__file__, vmx.__version__]))",
            ],
            cwd=target,
            timeout=_remaining(deadline, 60),
            env=env,
        )
    )
    location = Path(probe[0]).resolve()
    if not location.is_relative_to(venv.resolve()) or _is_inside(location, REPO_ROOT):
        raise StarterError(f"vmx imported from {location}, not from {venv}")
    if probe[1] != version:
        raise StarterError(f"vmx.__version__ is {probe[1]}, expected {version}")

    (target / "requirements.lock").write_text(
        render_python_lock(report, python_minor=python_minor), encoding="utf-8"
    )
    _run(
        [interpreter, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=target,
        timeout=_remaining(deadline, 120),
        env=env,
    )
    _run(
        [interpreter, "-m", "notes_app"],
        cwd=target,
        timeout=_remaining(deadline, 60),
        env=env,
    )
    pip_version = _run(
        [*pip, "--version"], cwd=target, timeout=_remaining(deadline, 30), env=env
    ).split()[1]
    return {
        "location": str(location),
        "pip_version": pip_version,
        "python_version": python_version,
        "python_minor": python_minor,
        "distributions": ", ".join(
            f"{name} {version_}" for name, version_, _ in report_distributions(report)
        ),
    }


# --------------------------------------------------------------------------
# SwiftPM checks (Swift package)
# --------------------------------------------------------------------------


def parse_ls_remote(output: str) -> dict[str, str]:
    """Map each tag to the commit it names; peeled ``^{}`` entries win."""
    tags: dict[str, str] = {}
    peeled: dict[str, str] = {}
    for line in output.splitlines():
        match = _LS_REMOTE_RE.match(line.strip())
        if match is None:
            continue
        sha, ref = match.groups()
        if ref.endswith("^{}"):
            peeled[ref.removesuffix("^{}")] = sha
        else:
            tags[ref] = sha
    tags.update(peeled)
    return tags


def swift_release_versions(tags: Mapping[str, str]) -> list[str]:
    """Return the Swift releases: versions with a ``swift-v`` and a ``v`` tag on one commit."""
    versions = []
    for tag, sha in tags.items():
        if not tag.startswith("swift-v"):
            continue
        version = tag.removeprefix("swift-v")
        if _SEMVER_RE.fullmatch(version) and tags.get(f"v{version}") == sha:
            versions.append(version)
    return sorted(versions, key=_version_key)


def scan_package_resolved(
    resolved: Mapping[str, object], version: str, url: str = SWIFT_PACKAGE_URL
) -> list[str]:
    """Return every pin in ``Package.resolved`` that is not the exact VMx release."""
    pins = resolved.get("pins")
    if not isinstance(pins, list):
        return ["Package.resolved has no 'pins' list"]
    issues: list[str] = []
    found = False
    for pin in pins:
        if not isinstance(pin, dict):
            issues.append("Package.resolved pin is not an object")
            continue
        identity = pin.get("identity")
        if pin.get("kind") != "remoteSourceControl":
            issues.append(f"{identity}: kind {pin.get('kind')!r} is not remoteSourceControl")
        if pin.get("location") != url:
            issues.append(f"{identity}: location {pin.get('location')!r} is not {url}")
        state = pin.get("state")
        if not isinstance(state, dict) or not isinstance(state.get("revision"), str):
            issues.append(f"{identity}: has no resolved revision")
            continue
        if identity == SWIFT_PACKAGE_IDENTITY:
            found = True
            if state.get("version") != version:
                issues.append(f"{identity}: resolved {state.get('version')!r}, expected {version}")
        else:
            issues.append(f"{identity}: is not a VMx dependency")
    if not found:
        issues.append(f"Package.resolved has no {SWIFT_PACKAGE_IDENTITY!r} pin")
    return issues


def resolved_revision(resolved: Mapping[str, object]) -> str | None:
    """Return the VMx pin's revision from ``Package.resolved``."""
    pins = resolved.get("pins")
    if not isinstance(pins, list):
        return None
    for pin in pins:
        if isinstance(pin, dict) and pin.get("identity") == SWIFT_PACKAGE_IDENTITY:
            state = pin.get("state")
            revision = state.get("revision") if isinstance(state, dict) else None
            return revision if isinstance(revision, str) else None
    return None


def show_dependencies_version(tree: Mapping[str, object]) -> tuple[str | None, str | None]:
    """Return the VMx version and URL from ``swift package show-dependencies``."""
    dependencies = tree.get("dependencies")
    if not isinstance(dependencies, list):
        return None, None
    for dependency in dependencies:
        if isinstance(dependency, dict) and dependency.get("identity") == SWIFT_PACKAGE_IDENTITY:
            version = dependency.get("version")
            url = dependency.get("url")
            return (
                version if isinstance(version, str) else None,
                url if isinstance(url, str) else None,
            )
    return None, None


def git_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an environment in which git and SwiftPM fail instead of prompting."""
    env = dict(os.environ if base is None else base)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    return env


def _ls_remote(git: str, *, timeout: float, refs: list[str] | None = None) -> dict[str, str]:
    args = [git, "ls-remote", "--tags", SWIFT_PACKAGE_URL, *(refs or [])]
    result = subprocess.run(
        args, check=False, capture_output=True, text=True, timeout=timeout, env=git_environment()
    )
    if result.returncode != 0:
        raise StarterError(f"git ls-remote {SWIFT_PACKAGE_URL} failed: {result.stderr.strip()}")
    return parse_ls_remote(result.stdout)


def latest_swift_version(git: str, *, timeout: float) -> str:
    """Return the newest Swift release tag on the public repository."""
    versions = swift_release_versions(_ls_remote(git, timeout=timeout))
    if not versions:
        raise StarterError(f"{SWIFT_PACKAGE_URL} has no matching swift-vX.Y.Z and vX.Y.Z tags")
    return versions[-1]


def verify_swift_package(
    target: Path, version: str, *, swift: str, git: str, deadline: float
) -> dict[str, str]:
    """Resolve the exact tag, check the pin, then build and run the smoke test."""
    tags = _ls_remote(
        git,
        timeout=_remaining(deadline, 60),
        refs=[f"refs/tags/v{version}*", f"refs/tags/swift-v{version}*"],
    )
    expected = tags.get(f"v{version}")
    if expected is None or tags.get(f"swift-v{version}") != expected:
        raise StarterError(
            f"tags v{version} and swift-v{version} must exist and name one commit; found {tags}"
        )

    # No shared repository cache: the clean room fetches from GitHub. git and
    # SwiftPM fail instead of waiting for a credential prompt.
    env = git_environment()
    _run(
        [swift, "package", "--disable-dependency-cache", "resolve"],
        cwd=target,
        timeout=_remaining(deadline, 300),
        env=env,
    )
    resolved = json.loads((target / "Package.resolved").read_text(encoding="utf-8"))
    issues = scan_package_resolved(resolved, version)
    if issues:
        raise StarterError("Package.resolved is not clean-room:\n- " + "\n- ".join(issues))
    revision = resolved_revision(resolved)
    if revision != expected:
        raise StarterError(f"resolved revision {revision}, but tag v{version} names {expected}")

    tree = json.loads(
        _run(
            [swift, "package", "show-dependencies", "--format", "json"],
            cwd=target,
            timeout=_remaining(deadline, 120),
            env=env,
        )
    )
    shown, url = show_dependencies_version(tree)
    if shown != version or url != SWIFT_PACKAGE_URL:
        raise StarterError(
            f"show-dependencies resolved VMx {shown} from {url}, "
            f"expected {version} from {SWIFT_PACKAGE_URL}"
        )

    _run([swift, "build"], cwd=target, timeout=_remaining(deadline, 600), env=env)
    _run([swift, "run", "NotesSmoke"], cwd=target, timeout=_remaining(deadline, 300), env=env)
    _run([swift, "run", "NotesApp"], cwd=target, timeout=_remaining(deadline, 300), env=env)
    swift_version = _run([swift, "--version"], cwd=target, timeout=_remaining(deadline, 30))
    first_line = next(
        (line for line in swift_version.splitlines() if "Swift version" in line), "Swift"
    )
    toolchain = re.sub(r"^.*?(Swift version \S+).*$", r"\1", first_line)
    return {"revision": revision, "swift_version": toolchain}


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------


def write_template(
    channel: str, version: str, target: Path, *, core_version: str | None = None
) -> list[Path]:
    """Copy the template files and render the manifest into ``target``."""
    source = template_dir(channel)
    written: list[Path] = []
    for relative in template_files(channel):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, destination)
        written.append(relative)
    manifest = MANIFEST_FILES[channel]
    if channel == "typescript-node":
        text = render_package_json(version)
    elif channel == "python-console":
        text = render_requirements(version)
    elif channel == "swift-package":
        text = render_swift_manifest(version)
    else:
        if core_version is None:
            raise ValueError("the react-vite channel needs a core version")
        text = render_react_package_json(version, core_version)
    (target / manifest).write_text(text, encoding="utf-8")
    written.append(Path(manifest))
    return sorted(written)


def _validate_options(
    channel: str,
    *,
    version: str | None,
    core_version: str | None,
    registry: str | None,
    browser_deps: bool,
) -> None:
    template_dir(channel)
    if browser_deps and channel != "react-vite":
        raise ValueError("--browser-deps applies only to the react-vite channel")
    if version is not None:
        require_version(version)
    if core_version is not None:
        if channel != "react-vite":
            raise ValueError("--core-version applies only to the react-vite channel")
        require_version(core_version)
    if registry is not None and channel not in NPM_CHANNELS:
        raise ValueError(f"--registry applies only to the npm channels {NPM_CHANNELS}")
    if channel == "python-console" and sys.version_info < (3, 10):
        raise StarterError("the python-console starter needs Python 3.10 or later")
    if channel == "swift-package" and platform.system() != "Darwin":
        raise StarterError("the swift-package starter needs macOS: VMx for Swift uses Combine")


def create_starter(
    channel: str,
    *,
    version: str | None = None,
    core_version: str | None = None,
    target: Path | None = None,
    registry: str | None = None,
    timeout_seconds: float = 900,
    browser_deps: bool = False,
) -> Path:
    """Generate and verify a starter; return its directory."""
    deadline = time.monotonic() + timeout_seconds
    # Reject bad arguments before any tool lookup or network access.
    _validate_options(
        channel,
        version=version,
        core_version=core_version,
        registry=registry,
        browser_deps=browser_deps,
    )
    if target is not None:
        target = validate_target(target)
    npm_registry = registry or DEFAULT_REGISTRY

    if channel in NPM_CHANNELS:
        npm = _which("npm")
        node = _which("node")
        if version is None:
            package = PACKAGE_NAME if channel == "typescript-node" else REACT_PACKAGE_NAME
            version = latest_version(
                npm, npm_registry, timeout=_remaining(deadline, 120), package=package
            )
        if channel == "react-vite" and core_version is None:
            core_version = latest_version(npm, npm_registry, timeout=_remaining(deadline, 120))
    elif channel == "python-console":
        executable, prefix, base = current_interpreter()
        require_interpreter_outside_checkout(executable, prefix=prefix, base_executable=base)
        if version is None:
            version = latest_pypi_version(timeout=_remaining(deadline, 60))
    else:
        swift = _which("swift")
        git = _which("git")
        if version is None:
            version = latest_swift_version(git, timeout=_remaining(deadline, 60))

    if target is None:
        target = validate_target(Path(tempfile.mkdtemp(prefix=f"vmx-starter-{channel}-")))
    target.mkdir(parents=True, exist_ok=True)
    pins = {
        "typescript-node": f"{PACKAGE_NAME}@{version}",
        "python-console": f"{PYTHON_PACKAGE_NAME}=={version} from PyPI",
        "swift-package": f"VMx {version} from {SWIFT_PACKAGE_URL}",
        "react-vite": f"{REACT_PACKAGE_NAME}@{version} and {PACKAGE_NAME}@{core_version}",
    }[channel]
    print(f"Generating {channel} starter for {pins} in {target}", flush=True)
    written = write_template(channel, version, target, core_version=core_version)
    print("Wrote " + ", ".join(path.as_posix() for path in written))

    if channel == "typescript-node":
        _finish_typescript_node(target, version, npm, node, npm_registry, deadline)
    elif channel == "react-vite":
        assert core_version is not None
        _finish_react_vite(
            target, version, core_version, npm, node, npm_registry, deadline, browser_deps
        )
    elif channel == "python-console":
        _finish_python_console(target, version, deadline)
    else:
        _finish_swift_package(target, version, swift, git, deadline)
    return target


def _finish_typescript_node(
    target: Path, version: str, npm: str, node: str, registry: str, deadline: float
) -> None:
    copies = verify_typescript_node(target, version, npm=npm, registry=registry, deadline=deadline)
    node_version = _run([node, "--version"], cwd=target, timeout=_remaining(deadline, 30))
    npm_version = _run([npm, "--version"], cwd=target, timeout=_remaining(deadline, 30))
    (target / "README.md").write_text(
        render_readme(
            version,
            node_version=node_version.strip().removeprefix("v"),
            npm_version=npm_version.strip(),
            platform_name=_platform_name(),
        ),
        encoding="utf-8",
    )
    print(f"OK: npm ls resolved {PACKAGE_NAME}@{version}, equal to the pin")
    for name, paths in copies.items():
        print(f"OK: one copy of {name}: {paths[0]}")
    print("OK: lockfile has no file:/link: references and resolves only from " + registry)
    print(f"OK: npm test and npm start exited 0; starter kept at {target}")


def _finish_react_vite(
    target: Path,
    version: str,
    core_version: str,
    npm: str,
    node: str,
    registry: str,
    deadline: float,
    browser_deps: bool,
) -> None:
    stack, copies, browser = verify_react_vite(
        target,
        version,
        core_version,
        npm=npm,
        registry=registry,
        deadline=deadline,
        browser_deps=browser_deps,
    )
    node_version = _run([node, "--version"], cwd=target, timeout=_remaining(deadline, 30))
    npm_version = _run([npm, "--version"], cwd=target, timeout=_remaining(deadline, 30))
    (target / "README.md").write_text(
        render_react_readme(
            version,
            core_version,
            resolved=stack,
            browser=browser,
            node_version=node_version.strip().removeprefix("v"),
            npm_version=npm_version.strip(),
            platform_name=_platform_name(),
        ),
        encoding="utf-8",
    )
    print(
        f"OK: npm ls resolved {REACT_PACKAGE_NAME}@{version} and "
        f"{PACKAGE_NAME}@{core_version}, equal to the pins"
    )
    for name, paths in copies.items():
        print(f"OK: one copy of {name}: {paths[0]}")
    print("OK: lockfile has no file:/link: references and resolves only from " + registry)
    print(f"OK: npm run build and the {browser} browser check passed; starter kept at {target}")


def _finish_python_console(target: Path, version: str, deadline: float) -> None:
    facts = verify_python_console(target, version, python=sys.executable, deadline=deadline)
    (target / "README.md").write_text(
        render_python_readme(
            version,
            python_version=facts["python_version"],
            python_minor=facts["python_minor"],
            pip_version=facts["pip_version"],
            platform_name=_platform_name(),
        ),
        encoding="utf-8",
    )
    print(f"OK: pip show and the install report agree on {PYTHON_PACKAGE_NAME} {version}")
    print(f"OK: vmx imported from the starter venv: {facts['location']}")
    print(f"OK: every distribution came from {PYPI_FILES_URL}: {facts['distributions']}")
    print(f"OK: unittest and python -m notes_app exited 0; starter kept at {target}")


def _finish_swift_package(
    target: Path, version: str, swift: str, git: str, deadline: float
) -> None:
    facts = verify_swift_package(target, version, swift=swift, git=git, deadline=deadline)
    (target / "README.md").write_text(
        render_swift_readme(
            version,
            revision=facts["revision"],
            swift_version=facts["swift_version"],
            platform_name=_platform_name(),
        ),
        encoding="utf-8",
    )
    print(f"OK: Package.resolved and show-dependencies resolved VMx {version}")
    print(f"OK: revision {facts['revision']} equals tags v{version} and swift-v{version}")
    print(f"OK: swift run NotesSmoke and NotesApp exited 0; starter kept at {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--channel", choices=CHANNELS, default=CHANNELS[0])
    parser.add_argument(
        "--version",
        help=(
            "exact version of the channel's VMx package: @thekaveh/vmx, PyPI vmx, the "
            "SwiftPM tag, or @thekaveh/vmx-react (default: the latest public release)"
        ),
    )
    parser.add_argument(
        "--core-version",
        help="react-vite only: exact @thekaveh/vmx version (default: the npm latest tag)",
    )
    parser.add_argument(
        "--target",
        type=Path,
        help="empty directory outside the checkout (default: a new temporary directory)",
    )
    parser.add_argument(
        "--registry", help=f"npm channels only: registry URL (default: {DEFAULT_REGISTRY})"
    )
    parser.add_argument(
        "--browser-deps",
        action="store_true",
        help="react-vite only: also install Chromium's system packages (Linux CI)",
    )
    parser.add_argument("--timeout", type=float, default=900, dest="timeout_seconds")
    args = parser.parse_args(argv)
    try:
        create_starter(
            args.channel,
            version=args.version,
            core_version=args.core_version,
            target=args.target,
            registry=args.registry,
            timeout_seconds=args.timeout_seconds,
            browser_deps=args.browser_deps,
        )
    except (
        OSError,
        StarterError,
        TimeoutError,
        ValueError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"ERROR: starter generation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
