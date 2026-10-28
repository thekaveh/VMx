# ADR 0163 — TypeScript `isTreeStructureChanged` raw-message predicate

- **Status:** Accepted
- **Date:** 2026-10-27
- **Spec version:** 3.30.0 (additive, TypeScript-only)
- **Amends:** ADR-0094 §2 items 1 and 2

## 1. Context

ADR-0094 added three TypeScript predicates for raw hub messages. Their scope is
the property, collection and construction-status messages, and each one
classifies with `instanceof`. No predicate classifies
`TreeStructureChangedMessage`. Tree bindings therefore filter it by hand or
with `instanceof`.

`instanceof` fails when an application installs two copies of the package.
This happens when an adapter package resolves its own copy of
`@thekaveh/vmx`. A tree binding in an adapter, such as a React or Vue children
hook, then ignores every tree message (#666, #672).

## 2. Decision

1. TypeScript exports a fourth predicate, `isTreeStructureChanged`, from the
   message barrel and the package root. It has three forms:

   - `isTreeStructureChanged(message)`, which narrows to
     `TreeStructureChangedMessage<unknown, unknown>`;
   - `isTreeStructureChanged(message, { sender, change? })`, which infers the
     sender type from the checked sender;
   - `isTreeStructureChanged(message, { change? })`.

1. The predicate classifies by shape, not only by class. A message matches when
   it is a `TreeStructureChangedMessage`, or when it has all of these:

   - an own `sender` property;
   - a string `senderName`;
   - a `change` of `"added"`, `"removed"` or `"reparented"`;
   - an own `affected` property;
   - an integer `index`.

   So a tree message from a second copy of the package still matches.

1. Constraints follow ADR-0094 §2 item 2. `sender` uses strict object identity,
   and `change` uses exact equality. Constraint presence uses own properties,
   so an explicit `undefined` compares exactly.

1. The unary overload makes the predicate a direct `Array.filter` and RxJS
   `filter` callback. A numeric callback index counts as no constraint, as in
   ADR-0094 §2 item 3.

1. The `affected` payload stays `unknown`. The sender constraint cannot prove
   its type. The shape check is type-safe only while the message class has no
   methods or private fields. A change to the class needs a new rule.

1. The three ADR-0094 predicates keep their `instanceof` classification. A
   change to them is a separate decision.

1. Spec 03 §7.3 lists the fourth predicate and its classification.

1. Like ADR-0094, this is an informative TypeScript-only API. It adds no
   conformance ID and no requirement for C#, Python, Swift or Rust.

## 3. Consequences

- Tree bindings can filter tree messages without a cast, also across two
  package copies.
- A plain object with the same shape also matches. The hub carries only
  messages that VMx or the application sends, so this does not change any
  existing filter.
- The conformance counts do not change.

## 4. Rejected alternatives

- **`instanceof` only, as ADR-0094 does:** this keeps the two-copy failure that
  motivated the ticket.
- **A type tag on the message class:** this changes the message shape in every
  flavor for a TypeScript packaging problem.
