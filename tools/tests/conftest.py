"""Test config for tools/. Adjusts sys.path so the script under test is importable."""

import importlib.util
import sys
from pathlib import Path

# Add tools/ to sys.path so we can import check_conformance_coverage as a module.
TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

# The script's filename uses a hyphen, so `import check_conformance_coverage` would
# normally fail. We pre-load the script under the underscore alias via importlib so
# the test module's plain `import` works. This conftest is the sole load path for
# the script-as-module in tests.
_SCRIPT = TOOLS_DIR / "check-conformance-coverage.py"
if _SCRIPT.exists() and "check_conformance_coverage" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("check_conformance_coverage", _SCRIPT)
    assert _spec is not None and _spec.loader is not None
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["check_conformance_coverage"] = _mod
    _spec.loader.exec_module(_mod)  # type: ignore[attr-defined]
