# ADR 0032 — `PropertyValueChangedMessages` helper (informative)

**Status:** Accepted (2026-05-28)
**Spec version:** introduced in 2.1.0

## 1. Context

Several legacy codebases shipped a `PropertyValueChangedMessages` or
`PropertyValueChangedMessagesFor` helper that returns an `IObservable<TProperty>` of
property values directly, rather than the full `PropertyChangedMessage` envelope.
Subscribers typically care about the current property value after each change, not
about the message metadata (sender name, property name string). The helper saves a
`.Select(m => getter(sender))` on the consumer side.

`PropertyChangedMessage` deliberately does not carry the new value (it carries only
the sender reference and property name, per the spec's §2.1 shape). The helper
therefore snapshots the property value from the sender at the moment the message
arrives — which is the value consumers want.

## 2. Options considered

1. **Skip** — consumers write `.OfType<PropertyChangedMessage<T>>().Where(...).Select(_ => sender.Property)` themselves.
1. **Add as normative API** — require every flavor to implement it with conformance IDs.
1. **Add as a small informative helper** in each flavor's messages module, with no conformance ID.

## 3. Decision

Option 3. The helper is per-flavor convenience; the underlying `Messages` stream and
`PropertyChangedMessage` are already conformance-tested (HUB-NNN and PROP-NNN). This
ADR records the helper's intent and per-flavor shape but adds no normative conformance ID.

## 4. Per-flavor shape

| Flavor     | Name                                  | Signature sketch                                                                                   |
| ---------- | ------------------------------------- | -------------------------------------------------------------------------------------------------- |
| C#         | `PropertyValueChangedMessagesFor`     | `IMessageHub.PropertyValueChangedMessagesFor<TSource, TProperty>(source, expr)` (extension method) |
| Python     | `property_value_changed_messages_for` | `property_value_changed_messages_for(hub, source, property_name)` (module-level function)          |
| TypeScript | `propertyValueChangedMessagesFor`     | `propertyValueChangedMessagesFor(hub, source, propertyName)` (named export)                        |
| Swift      | `propertyValueChangedMessagesFor`     | `MessageHubProtocol.propertyValueChangedMessagesFor(source, propertyName, getter:)` (extension)    |

All four: filter the hub's `messages` stream to matching `PropertyChangedMessage`
instances (identity check on sender), then snapshot the current property value from
the sender at delivery time.

## 5. Consequences

- A small per-flavor helper in each flavor's `messages/` module.
- A short "Convenience helpers" subsection added to `spec/03-messages.md`.
- No new conformance IDs.
- Future evolution of the underlying hub APIs may obviate this helper; that is
  acceptable for an informative item.

## 6. Rejected alternatives

- **Normative API with conformance IDs**: The helper is too thin and its shape is
  flavor-idiomatic (expression vs string vs keyof). Normalizing the signature across
  flavors would either require awkward expression-tree support in Python/TS or lose
  type safety in C#. Keeping it informative avoids that tension.
- **Skip entirely**: The helper is useful enough to ship — it was present in legacy
  codebases and reduces boilerplate in subscribe chains. Informative status lets each
  flavor implement it idiomatically without locking in a cross-flavor contract.
