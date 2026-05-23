# Conformance tests (Python flavor)

These tests assert the language-neutral conformance catalog from
`spec/12-conformance.md`. Each test method carries a
`@pytest.mark.conformance("<ID>")` marker identifying the catalog row it
asserts. The whole catalog must be covered for a conformant release; coverage
is enforced in CI via `tools/check-conformance-coverage.py --require python`.
