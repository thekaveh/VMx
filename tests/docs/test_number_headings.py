from scripts.docs.number_headings import number_descendant_headings


def test_number_descendant_headings_is_hierarchical_and_idempotent() -> None:
    source = """# 7.2. Page

## Existing section

### 4.7. Stale detail number

## Next section

```markdown
## Example heading
```
"""
    expected = """# 7.2. Page

## 7.2.1. Existing section

### 7.2.1.1. Stale detail number

## 7.2.2. Next section

```markdown
## Example heading
```
"""
    assert number_descendant_headings(source, "7.2") == expected
    assert number_descendant_headings(expected, "7.2") == expected


def test_number_descendant_headings_rejects_missing_parent() -> None:
    source = "# 1. Page\n\n### Detail without a section\n"

    try:
        number_descendant_headings(source, "1")
    except ValueError as error:
        assert "no H2 parent" in str(error)
    else:
        raise AssertionError("missing parent must be rejected")
