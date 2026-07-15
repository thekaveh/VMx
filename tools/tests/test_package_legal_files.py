"""Keep flavor package legal files synchronized with repository sources."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIRS = (
    ROOT / "langs/python",
    ROOT / "langs/typescript",
    ROOT / "langs/rust",
)


def test_package_legal_files_match_repository_sources() -> None:
    for package_dir in PACKAGE_DIRS:
        for name in ("LICENSE", "NOTICE"):
            assert (package_dir / name).read_bytes() == (ROOT / name).read_bytes()


def test_python_declares_pep_639_license_files() -> None:
    pyproject = (ROOT / "langs/python/pyproject.toml").read_text(encoding="utf-8")

    assert 'license = "Apache-2.0"' in pyproject
    assert 'license-files = ["LICENSE", "NOTICE"]' in pyproject
