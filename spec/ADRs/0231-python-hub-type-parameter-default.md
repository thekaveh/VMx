# ADR 0231 — Python hub type parameters default to `Message`

- **Status:** Accepted
- **Date:** 2026-11-15
- **Spec version:** 3.30.0 (Python flavor and ADR registry only; no spec chapter, conformance ID or HISTORY change)
- **Clarifies:** [ADR-0009](0009-cross-flavor-divergence-catalogue.md) (§2, the `MessageHub` parameterisation row). Related: #1903 (the issue this ADR implements), #1582 (a typed stream of one application message type, a separate change to the same hub).

## 1. Context

`MessageHub` is generic over `_THubMessage`, a type variable with a bound and no default. `MessageHubProto` and `TransactionalMessageHubProto` are generic over `TMessage`, which has the same shape. Under `mypy --strict`, a bare `hub = MessageHub()` needs an annotation (`var-annotated`), and a bare `MessageHub` parameter is an error (`type-arg`). Consumers therefore write `MessageHub[Message]` on most hub declarations.

Only `MessageHub.send` uses the type variable. `MessageHub.messages` and the protocol `messages` property are typed `Observable[Message]` for every parameterisation, so `Message` is the parameter that consumers use.

ADR-0009 records the class-generic `MessageHub[Message]` shape as the idiomatic Python form. It does not discuss a default.

PEP 696 type parameter defaults let a bare generic mean `Generic[Default]`. `typing.TypeVar` accepts `default=` only from Python 3.13, and the package supports 3.10 to 3.14. `typing_extensions.TypeVar` accepts `default=` from typing-extensions 4.4.0. Release 4.11.0 fixed the runtime behavior of defaulted type variables, and 4.12.0rc1 completed the PEP 696 runtime (`NoDefault`, `has_default()`). The one runtime dependency of the package, `reactivex`, requires only `typing-extensions>=4.1.1`, so that transitive floor does not guarantee `default=`.

## 2. Decision

1. **Default on the hub type variable.** `_THubMessage` is declared with `bound=Message, default=Message`, so a bare `MessageHub` means `MessageHub[Message]`. Reason: a bare form then means the parameterisation that consumers already write, and no consumer changes its code.
1. **One declaration for every Python version.** `_THubMessage` and `TMessage` import `TypeVar` from `typing_extensions` on Python 3.10 to 3.14, not from `typing`. Reason: a single declaration covers every version. The alternative, a version-conditional choice between `typing.TypeVar` and `typing_extensions.TypeVar`, needs two declarations for one contract and a conditional dependency. The simplest rule that is uniform is the single declaration.
1. **Explicit dependency with a floor of 4.12.0.** `langs/python/pyproject.toml` declares `typing-extensions>=4.12.0` in `[project] dependencies`. The package does not rely on the copy that `reactivex` brings. Reason for the floor: 4.4.0 is the first release with the parameter, and 4.12.0 is the first release whose runtime for defaulted type variables is complete (decision context in section 1). The dependency is unconditional, so it also applies on Python 3.13 and later, where `typing.TypeVar` would work alone. That cost buys decision 2's single declaration.
1. **Same default on the protocols.** `TMessage`, the type variable of `MessageHubProto` and `TransactionalMessageHubProto`, has `default=Message` as well. It stays contravariant. Reason: one rule for every hub type variable. A bare `MessageHubProto` annotation then means `MessageHubProto[Message]`, the same as the hub. The protocols use the same bound, and `Message` is the parameter that consumers use.
1. **A typing contract, checked by mypy.** `langs/python/tests/typing/message_hub_default.py` asserts the bare forms with `typing_extensions.assert_type`. `.github/workflows/python.yml` runs `mypy --strict` on it in a step after the `Mypy` step. Reason: a default is a static property. pytest does not collect the file, because its name is not `test_*.py`, and the public API baseline does not render a bare annotation. The mypy step is the only check that fails when the default is removed.
1. **Public API baseline unchanged.** `langs/python/api/vmx.api.txt` has no diff on Python 3.12. The base of `MessageHub` still renders `typing.Generic[~_THubMessage]`, and the protocol bases still render with their type variables. The baseline therefore does not guard the default, and decision 5 does.
1. **Runtime behavior unchanged.** `MessageHub` and the protocols change only in their type variables. Explicit parameterisations such as `MessageHub[Message]` keep their meaning. Existing annotations in the docs and the examples remain valid.
1. **ADR-0009 updated in place.** The `MessageHub` parameterisation row now says that a bare `MessageHub` means `MessageHub[Message]`. The row's Status line and registry cell carry the back-link `clarified by ADR-0231`, as ADR README section 2.3 requires. Reason: the row is the cross-flavor record of this shape, and this ADR holds the reasons for the change.
1. **No conformance ID, spec chapter, HISTORY entry or version change.** The change is typing-only in the Python flavor. No `spec/NN-*.md` chapter changes, and the source version stays 3.30.0.
1. **Locks record the new dependency.** `langs/python/uv.lock` and four example locks (`examples/python`, `examples/python/textual/inspector`, `examples/python/textual/notes_showcase` and `examples/python/nicegui/notes_showcase`) change only in the `vmx` metadata: the new `typing-extensions` entry and its `>=4.12.0` specifier. Reason: each example installs `vmx` by path and records its dependency list, and `uv lock --locked` fails until the lock is updated. No pinned package version changes.
1. **CHANGELOG.** `langs/python/CHANGELOG.md` records the change under `### Changed` in the `[3.30.0] — unreleased source version` section (CONTRIBUTING section 4.3).

## 3. Consequences

- A bare `MessageHub()`, a bare `MessageHub` parameter and a bare `MessageHubProto` or `TransactionalMessageHubProto` annotation type-check under `mypy --strict` as `Message` parameterisations. Consumers can drop the annotation.
- The Python flavor's typing-extensions floor rises to 4.12.0. pip upgrades a consumer's older copy when it resolves the package.
- Each Python CI matrix cell runs one more `mypy --strict` step.
- The Swift and Rust hubs and the C# and TypeScript shapes are unchanged. The bare form exists only in Python, as ADR-0009 records.

## 4. Rejected alternatives

- **`typing.TypeVar` on Python 3.13 and later, `typing_extensions.TypeVar` below 3.13.** Two declarations for one contract, plus a conditional dependency marker. Rejected in favor of decision 2.
- **The issue's proposed floor, `typing-extensions>=4.4.0`.** Rejected: releases 4.4.0 to 4.10.0 predate the runtime corrections in 4.11.0 and 4.12.0rc1.
- **The transitive copy from `reactivex`.** Rejected: `reactivex` 4.0.4 allows `typing-extensions>=4.1.1`, so it does not guarantee `default=`.
- **`default=Any` or `default=object`.** Rejected: the bare forms would mean `MessageHub[Any]` or `MessageHub[object]`, not `Message`. The typing contract rejects `Any` (verified by a mutation before the change was committed).
- **Editing ADR-0009 alone, with no new ADR.** Issue #1903 proposed this. Rejected as the only record: the reasons for the default, the floor and the protocol choice need an ADR that ADR-0009 can link to. ADR-0009 keeps the row and gains the back-link.
