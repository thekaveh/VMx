"""Keep the AsyncResourceVM loader-cancellation recipe identical to its test (#334)."""

import re
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDE = REPO_ROOT / "docs/content/primitives/state-reactive-helpers.md"
RECIPE_TEST = REPO_ROOT / "langs/python/tests/unit/state/test_async_resource_cancellation_recipe.py"


def test_cancellation_recipe_is_the_executed_test() -> None:
    source = RECIPE_TEST.read_text(encoding="utf-8")
    region = re.search(r"# docs-recipe:start\n(.*?)\n\s*# docs-recipe:end", source, re.S)
    assert region, "the recipe test lost its docs-recipe markers"

    guide = GUIDE.read_text(encoding="utf-8")
    blocks = [
        block
        for block in re.findall(r"```python\n(.*?)```", guide, re.S)
        if "async def load_profile" in block
    ]
    assert len(blocks) == 1, "state-reactive-helpers.md must show the recipe once"
    assert blocks[0] == textwrap.dedent(region.group(1)) + "\n"
