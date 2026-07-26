import ast
from pathlib import Path


def test_every_subprocess_run_has_a_timeout() -> None:
    root = Path(__file__).resolve().parents[2]
    missing: list[str] = []
    for base in (root / "docs", root / "scripts", root / "tools", root / "tests"):
        for path in base.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                if not (
                    isinstance(function, ast.Attribute)
                    and isinstance(function.value, ast.Name)
                    and function.value.id == "subprocess"
                    and function.attr == "run"
                ):
                    continue
                if not any(keyword.arg == "timeout" for keyword in node.keywords):
                    missing.append(f"{path.relative_to(root)}:{node.lineno}")

    assert missing == [], "subprocess.run calls without timeout: " + ", ".join(missing)
