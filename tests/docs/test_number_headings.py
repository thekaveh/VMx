from scripts.docs.number_headings import number_descendant_headings


def test_number_descendant_headings_is_hierarchical_and_idempotent() -> None:
    source = """# 7.2. Page

## Existing section

### 4.7. Stale detail number

### 7.2.1.2. 2.1 Option A

## Next section

```markdown
## Example heading
```
"""
    expected = """# 7.2. Page

## 7.2.1. Existing section

### 7.2.1.1. Stale detail number

### 7.2.1.2. Option A

## 7.2.2. Next section

```markdown
## Example heading
```
"""
    assert number_descendant_headings(source, "7.2") == expected
    assert number_descendant_headings(expected, "7.2") == expected


def test_number_descendant_headings_supports_standalone_documents() -> None:
    source = "# Gallery\n\n## C#\n\n### Console\n\n## Python\n"
    expected = "# Gallery\n\n## 1. C#\n\n### 1.1. Console\n\n## 2. Python\n"

    assert number_descendant_headings(source, None) == expected
    assert number_descendant_headings(expected, None) == expected


def test_number_descendant_headings_rejects_missing_parent() -> None:
    source = "# 1. Page\n\n### Detail without a section\n"

    try:
        number_descendant_headings(source, "1")
    except ValueError as error:
        assert "no H2 parent" in str(error)
    else:
        raise AssertionError("missing parent must be rejected")
