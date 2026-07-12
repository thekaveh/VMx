# 7.7. Cross-Language Naming

VMx keeps one conceptual API shape across the supported source flavors. The
names shift only to match the host language idiom.

## Core Translation Table

| Concept            | C#                         | Python                        | TypeScript                 | Swift                      | Rust                           |
| ------------------ | -------------------------- | ----------------------------- | -------------------------- | -------------------------- | ------------------------------ |
| Casing             | PascalCase                 | snake_case                    | camelCase                  | camelCase                  | snake_case methods, Rust types |
| Modeled leaf       | `ComponentVM<M>`           | `ComponentVMOf[M]`            | `ComponentVMOf<M>`         | `ComponentVMOf<M>`         | `ComponentVm<M>`               |
| Builder entry      | `Builder()`                | `builder()`                   | `builder()`                | `builder()`                | direct constructors / builders |
| Command requery    | `RaiseCanExecuteChanged()` | `raise_can_execute_changed()` | `raiseCanExecuteChanged()` | `raiseCanExecuteChanged()` | `raise_can_execute_changed()`  |
| Status property    | `Status`                   | `status`                      | `status`                   | `status`                   | `status()`                     |
| Null hub singleton | `NullMessageHub.Instance`  | `NULL_MESSAGE_HUB`            | `NullMessageHub.INSTANCE`  | `NullMessageHub.INSTANCE`  | `NullMessageHub::hub()`        |

## Serviced Collection Mutations

`ServicedObservableCollection` has the same seven mutation concepts in every
flavor. Existing array- or indexer-style aliases remain available where shown.

| Concept      | C#                  | Python        | TypeScript                   | Swift                                  | Rust          |
| ------------ | ------------------- | ------------- | ---------------------------- | -------------------------------------- | ------------- |
| Add          | `Add`               | `append`      | `push`                       | `append`                               | `push`        |
| Remove value | `Remove`            | `remove`      | `remove`                     | `remove`                               | `remove`      |
| Remove index | `RemoveAt`          | `remove_at`   | `removeAt`                   | `removeAt`                             | `remove_at`   |
| Replace      | indexer / `Replace` | `replace`     | `replace` (`setAt` retained) | `replace(at:with:)` (`setAt` retained) | `replace`     |
| Replace all  | `ReplaceAll`        | `replace_all` | `replaceAll`                 | `replaceAll`                           | `replace_all` |
| Move         | `Move`              | `move`        | `move`                       | `move(from:to:)`                       | `move_item`   |
| Clear        | `Clear`             | `clear`       | `clear`                      | `clear`                                | `clear`       |

The keyed serviced type inherits this ordered shape. Host-specific conveniences
also remain available: C# `Insert`, Python integer/slice `MutableSequence`
operations and `reverse`, TypeScript `pop` and `splice`, Swift `removeLast` and
Equatable value removal, and Rust's existing surface without a new positional
insert.

## Keyed Serviced Collections

| Concept            | C#                           | Python         | TypeScript | Swift         | Rust           |
| ------------------ | ---------------------------- | -------------- | ---------- | ------------- | -------------- |
| Projector argument | `keySelector`                | `key_of`       | `keyOf`    | `keyOf`       | `key_of`       |
| Indexed read       | indexer                      | `items[i]`     | `at`       | `at`          | `get(usize)`   |
| Keyed lookup       | `TryGetValue`                | `get`          | `get`      | `get`         | `get_by_key`   |
| Membership         | `ContainsKey`                | `contains_key` | `has`      | `containsKey` | `contains_key` |
| Add-or-replace     | `Upsert`                     | `upsert`       | `upsert`   | `upsert`      | `upsert`       |
| Keyed deletion     | `RemoveKey`                  | `delete`       | `delete`   | `delete`      | `remove_key`   |
| Missing delete     | `false`                      | `false`        | `false`    | `false`       | `None`         |
| Upsert result      | `true` Add / `false` Replace | same           | same       | same          | same           |

Construction is `new ...(keySelector, hub?, comparer?)` in C#,
`...(key_of, hub=None)` in Python, `new ...({ keyOf, hub? })` in TypeScript,
`...(keyOf:hub:)` in Swift, and `new(owner_id, key_of)` or
`with_hub(owner_id, hub, key_of)` in Rust. Rust's keyed spelling is
`get_by_key(&K)` because its inherited `get(usize)` already means indexed read
and Rust does not overload methods. Rust keys need `Eq + Hash + Send`, not
`Clone`.

In every flavor the projector result is captured per membership. Mutating an
item does not change that captured key; indexed replacement is an explicit
rekey at the same position. Upserting the same instance after its projected
key changes may therefore add a second membership. Duplicate or projector
failure is atomic. A successful operation commits items, keys, and the index,
then delivers locally before publishing to the optional external hub.

## Practical Notes

- The modeled-type name is the one structural divergence: C# keeps the generic
  suffix on `ComponentVM<M>`, while Python, TypeScript, and Swift expose a
  distinct `ComponentVMOf` name.
- Hub `PropertyChangedMessage` property names follow the flavor idiom:
  `"IsValid"` in C#, `"is_valid"` in Python, and `"isValid"` in TypeScript and
  Swift. Rust uses snake_case strings such as `"is_valid"`.
- The collections `"Count"` channel is a deliberate spec-literal exception; it
  does not get translated to the local casing style.
- Python keeps list-style `remove`: it returns `None` and raises `ValueError`
  when the value is missing. Value removal returns `bool` in the other flavors.
- Rust's serviced collection is a distinct type with an always-present local
  message stream and an optional external hub; it is not an alias for
  `ObservableList`.
- Both serviced collection types are caller-owned data containers. They do not
  implement VM child-collection lifecycle interfaces, dispose stored items, or
  gain a collection batch scope. An external hub transaction defers only hub
  delivery; local changes remain immediate.

## How To Use This Page

- Translate a snippet with this table first.
- Confirm the full local surface in the flavor README when the example moves
  beyond the shared core shape.
- Use [Quickstart](../quickstart.md) when you want same-concept examples across
  flavors in one place.
