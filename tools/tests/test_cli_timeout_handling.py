"""Timeout handling at maintenance-tool CLI boundaries."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


push_wiki = _load("push_wiki_timeout", "scripts/docs/push_wiki.py")


def test_wiki_cli_reports_subprocess_timeout(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        push_wiki,
        "push_wiki",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("git", 1)),
    )
    monkeypatch.setattr(sys, "argv", ["push_wiki"])

    assert push_wiki.main() == 2
    assert "unable to synchronize wiki" in capsys.readouterr().err
