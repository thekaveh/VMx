# ADR 0160 — `whenPropertyChanged` accepts several property names

- **Status:** Accepted
- **Date:** 2026-10-27
- **Spec version:** 3.30.0

## 1. Context

`whenPropertyChanged(hub, sender, propertyName)` (spec 03 §7.2, ADR-0050) takes
one property name in C#, Python, TypeScript and Swift. A view model that reacts
to two or three properties of one child therefore writes its own filter over
the hub. Heimdall reports 18 such filters (#664). Rust has no such helper and
uses `MessageHub::subscribe`.

## 2. Decision

Each of the four flavors adds a multi-name form. It takes the same `hub` and
`sender` and several property names.

1. A message matches when its sender is `sender` by identity and its property
   name equals any of the given names. Names match exactly and use the
   flavor's idiom, as in the single-name form. No flavor normalizes them.
1. Each subscription to the result makes one subscription to the hub's
   `Messages` stream. Disposing that subscription stops every name.
1. Each matching message is emitted once, in hub order. A name that appears
   more than once in the list does not emit a message twice.
1. The helper copies the names when it is called. A later change to the
   caller's list has no effect.
1. At least one name is required. A call with none is a caller error.
1. A single-name call behaves as before.

The per-flavor shapes are these:

| Flavor     | Multi-name form                                                                       | No names                         |
| ---------- | ------------------------------------------------------------------------------------- | -------------------------------- |
| C#         | `WhenPropertyChanged(this IMessageHub, object sender, params string[] propertyNames)` | `ArgumentException`              |
| Python     | `when_property_changed(hub, sender, property_name, *property_names)`                  | `TypeError` from the interpreter |
| TypeScript | `whenPropertyChanged(hub, sender, propertyName: string \| readonly string[])`         | `RangeError`                     |
| Swift      | `whenPropertyChanged(_ sender: AnyObject, _: String, _: String, _: String...)`        | Does not compile                 |

- **C#.** The `params string[]` overload sits next to the `string` overload.
  A call with one string argument binds to the `string` overload, because C#
  prefers a method that applies in its normal form over one that applies only
  in its expanded form. A call can also pass a `string[]`. A null array raises
  `ArgumentNullException`. An empty array, or a null element, raises
  `ArgumentException`. The change is binary compatible but has a small source
  break:
  - A call whose only name is the `null` literal, `null!` or `default` is
    ambiguous between the overloads and must cast it. That call threw
    `ArgumentNullException` before.
  - A method group with no target type, such as
    `var f = MessageHubExtensions.WhenPropertyChanged;`, no longer compiles.
  - A `cref` that names the method group without parameters is ambiguous and
    must name the parameter list.
  - A call with no names, such as `hub.WhenPropertyChanged(sender)`, now
    compiles and raises `ArgumentException`. Before, it did not compile.
- **Python.** The existing function gains `*property_names` after
  `property_name`. A single-name call is unchanged, and a sequence is passed as
  `*names`. A call without names raises the interpreter's `TypeError` for the
  missing `property_name` argument. That is Python's argument error, so the
  function adds no check of its own.
- **TypeScript.** The `propertyName` parameter widens to
  `string | readonly string[]`. A string keeps the single-name path unchanged.
  An empty array raises `RangeError`, because the type is correct and only the
  value is out of range.
- **Swift.** The overload takes two names and then a variadic list. One name
  binds only to `whenPropertyChanged(_:_:)`, and no names do not compile. So no
  call is ambiguous and no call needs a runtime check. A single variadic
  `String...` overload was rejected: a one-name call would depend on overload
  ranking, and a call with no names would compile and need a trap.

The multi-name form is informative, like the single-name form (ADR-0050 §2.1).
It adds no conformance ID. Each flavor's existing helper test file covers it.
Rust stays without the helper (spec 03 §7.2).

## 3. Consequences

- A view model can watch several properties of one child with one call and
  one hub subscription.
- No message changes. The hub's `Messages` stream stays the
  conformance-tested contract, and no conformance ID is added.
- C# code that passes a null literal as the only name, takes the method group
  without a target type, or uses a parameterless `cref` must name the overload
  it means. No such call worked before: a null name already threw.
- Rust keeps its filter over `MessageHub::subscribe`.
