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
def _preload(script_filename: str, module_alias: str) -> None:
    """Pre-load a hyphenated-name script under an importable underscore alias."""
    script = TOOLS_DIR / script_filename
    if script.exists() and module_alias not in sys.modules:
        spec = importlib.util.spec_from_file_location(module_alias, script)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_alias] = mod
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]


# Pre-load all check-*.py scripts under hyphen-stripped aliases.
_preload("check-conformance-coverage.py", "check_conformance_coverage")
_preload("check-axaml-codebehind.py", "check_axaml_codebehind")
_preload("check-textual-views.py", "check_textual_views")
_preload("check-layer-imports.py", "check_layer_imports")
_preload("check-showcase-parity.py", "check_showcase_parity")
_preload("check-version-consistency.py", "check_version_consistency")
_preload("check-python-fixture-sync.py", "check_python_fixture_sync")
_preload("check-rust-fixture-sync.py", "check_rust_fixture_sync")
_preload("check-swift-package-sync.py", "check_swift_package_sync")
_preload("check-typescript-package.py", "check_typescript_package")
_preload("check-nuget-package.py", "check_nuget_package")
_preload("smoke-swiftpm-consumer.py", "smoke_swiftpm_consumer")
_preload("smoke-npm-consumer.py", "smoke_npm_consumer")
_preload("smoke-nuget-consumer.py", "smoke_nuget_consumer")
