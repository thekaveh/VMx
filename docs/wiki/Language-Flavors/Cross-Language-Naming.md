# Cross-Language Naming

VMx keeps one conceptual API shape across all four supported flavors. Names
shift only to match the host language idiom.

## Core Translation Table

| Concept            | C#                        | Python             | TypeScript                | Swift                     |
| ------------------ | ------------------------- | ------------------ | ------------------------- | ------------------------- |
| Casing             | PascalCase                | snake_case         | camelCase                 | camelCase                 |
| Modeled leaf       | `ComponentVM<M>`          | `ComponentVMOf[M]` | `ComponentVMOf<M>`        | `ComponentVMOf<M>`        |
| Builder entry      | `Builder()`               | `builder()`        | `builder()`               | `builder()`               |
| Null hub singleton | `NullMessageHub.Instance` | `NULL_MESSAGE_HUB` | `NullMessageHub.INSTANCE` | `NullMessageHub.INSTANCE` |

## Notable Exceptions

- hub property names follow local idiom
- collection `"Count"` stays a spec-literal channel

## Related Pages

- \[[Quickstart|Getting-Started/Quickstart]\]
- \[[Framework Primitives|Framework-Primitives/Framework-Primitives]\]
