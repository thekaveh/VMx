# Shared Fixtures

Shared JSON fixtures under `spec/fixtures/` are consumed across the language
flavors for runtime loading and conformance validation.

## Important Rules

- Python tracks `lifecycle-transitions.json` under
  `langs/python/src/vmx/lifecycle/_data/`
- TypeScript syncs copied fixtures through `npm run sync-fixtures`
- C# embeds runtime fixture data and copies conformance inputs
- Swift ships all four JSON resources under `Bundle.module`

## Related Pages

- [[Spec Source Of Truth|Specification-and-Conformance/Spec-Source-Of-Truth]]
- [[Conformance Workflow|Specification-and-Conformance/Conformance-Workflow]]
