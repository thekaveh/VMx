# Cross-Language Naming

VMx keeps one conceptual API shape across the supported source flavors. The
names shift only to match the host language idiom.

## Core Translation Table

| Concept            | C#                        | Python             | TypeScript                | Swift                     | Rust                           |
| ------------------ | ------------------------- | ------------------ | ------------------------- | ------------------------- | ------------------------------ |
| Casing             | PascalCase                | snake_case         | camelCase                 | camelCase                 | snake_case methods, Rust types |
| Modeled leaf       | `ComponentVM<M>`          | `ComponentVMOf[M]` | `ComponentVMOf<M>`        | `ComponentVMOf<M>`        | `ComponentVm<M>`               |
| Builder entry      | `Builder()`               | `builder()`        | `builder()`               | `builder()`               | direct constructors / builders |
| Status property    | `Status`                  | `status`           | `status`                  | `status`                  | `status()`                     |
| Null hub singleton | `NullMessageHub.Instance` | `NULL_MESSAGE_HUB` | `NullMessageHub.INSTANCE` | `NullMessageHub.INSTANCE` | `NullMessageHub::hub()`        |

## Practical Notes

- The modeled-type name is the one structural divergence: C# keeps the generic
  suffix on `ComponentVM<M>`, while Python, TypeScript, and Swift expose a
  distinct `ComponentVMOf` name.
- Hub `PropertyChangedMessage` property names follow the flavor idiom:
  `"IsValid"` in C#, `"is_valid"` in Python, and `"isValid"` in TypeScript and
  Swift. Rust uses snake_case strings such as `"is_valid"`.
- The collections `"Count"` channel is a deliberate spec-literal exception; it
  does not get translated to the local casing style.

## How To Use This Page

- Translate a snippet with this table first.
- Confirm the full local surface in the flavor README when the example moves
  beyond the shared core shape.
- Use [Quickstart](../quickstart.md) when you want same-concept examples across
  flavors in one place.
