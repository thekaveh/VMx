# ADR 0231 — Python hub type parameters default to `Message`

- **Status:** Accepted
- **Date:** 2026-11-15
- **Spec version:** 3.30.0 (Python flavor and ADR registry only; no spec chapter, conformance ID or HISTORY change)
- **Clarifies:** [ADR-0009](0009-cross-flavor-divergence-catalogue.md) (§2, the `MessageHub` parameterisation row). Related: #1903 (the issue this ADR implements), #1582 (a typed stream of one application message type, a separate change to the same hub).

## 1. Context

`MessageHub` is generic over `_THubMessage`, a type variable with a bound and no default. `MessageHubProto` and `TransactionalMessageHubProto` are generic over `TMessage`, which has the same shape. Under `mypy --strict`, a bare `hub = MessageHub()` needs an annotation (`var-annotated`), and a bare `MessageHub` parameter is an error (`type-arg`). Consumers therefore write `MessageHub[Message]` on most hub declarations.

Only `MessageHub.send` uses the type variable. `MessageHub.messages` and the protocol `messages` property are typed `Observable[Message]` for every parameterisation, so `Message` is the parameter that consumers use.

ADR-0009 records the class-generic `MessageHub[Message]` shape as the idiomatic Python form. It does not discuss a default.

PEP 696 type parameter defaults let a bare generic mean `Generic[Default]`. `typing.TypeVar` accepts `default=` only from Python 3.13, and the package supports 3.10 to 3.14. `typing_extensions.TypeVar` accepts `default=` from typing-extensions 4.4.0, but the release note alone does not set the floor, because the 4.4.0 class fails on Python 3.13. The checks below ran on 2026-11-15 in scratch virtual environments, with the `vmx` source on the path:

- **Python 3.10.** typing-extensions 4.4.0 imports `vmx`, and both defaults resolve to `Message`. With typing-extensions 4.12.0 the full test suite passes (2467 tests). The suite cannot start at 4.4.0, because the test tooling (`pytest-asyncio`) needs a newer typing-extensions, so 4.4.0 was checked with the import probe only.
- **Python 3.13.** typing-extensions 4.4.0 and 4.5.0 fail at import (`TypeError: type 'typing.TypeVar' is not an acceptable base type`). Releases 4.6.0, 4.7.0, 4.8.0, 4.9.0, 4.10.0 and 4.11.0 import, but creating a defaulted `TypeVar` fails (`AttributeError: attribute '__default__' of 'typing.TypeVar' objects is not writable`). Typing-extensions 4.12.0 creates the defaulted `TypeVar`, and both defaults resolve to `Message` for `vmx`.
- **Python 3.14.** typing-extensions 4.12.0 creates the defaulted `TypeVar`, and both defaults resolve to `Message` for `vmx`.
- At runtime `vmx` imports only `TypeVar` from typing-extensions. `assert_type` appears only in the mypy test file, which pytest does not run.
- `vmx` does not pin the copy of typing-extensions that `reactivex` brings, so that copy may be any release, including the releases that fail on Python 3.13.

## 2. Decision

1. **Default on the hub type variable.** `_THubMessage` is declared with `bound=Message, default=Message`, so a bare `MessageHub` means `MessageHub[Message]`. Reason: a bare form then means the parameterisation that consumers already write, and no consumer changes its code.
1. **One declaration for every Python version.** `_THubMessage` and `TMessage` import `TypeVar` from `typing_extensions` on Python 3.10 to 3.14, not from `typing`. Reason: a single declaration covers every version. The alternative, a version-conditional choice between `typing.TypeVar` and `typing_extensions.TypeVar`, needs two declarations for one contract and a conditional dependency. The simplest rule that is uniform is the single declaration.
1. **Explicit dependency with a floor of 4.12.0.** `langs/python/pyproject.toml` declares `typing-extensions>=4.12.0` in `[project] dependencies`. This is a new explicit runtime dependency. Before this change the package declared no typing-extensions dependency and used the copy that `reactivex` brings. The floor is the lowest release that creates a defaulted `TypeVar` on Python 3.13 and 3.14 among those checked in section 1. Releases 4.4.0 to 4.11.0 were all checked and all fail on 3.13. The dependency is unconditional, so it also applies on Python 3.13 and later, where `typing.TypeVar` would work alone. That cost buys decision 2's single declaration.
1. **Same default on the protocols.** `TMessage`, the type variable of `MessageHubProto` and `TransactionalMessageHubProto`, has `default=Message` as well. It stays contravariant. Reason: one rule for every hub type variable. A bare `MessageHubProto` annotation then means `MessageHubProto[Message]`, the same as the hub. The protocols use the same bound, and `Message` is the parameter that consumers use.
1. **A typing contract, checked by mypy.** `langs/python/tests/typing/message_hub_default.py` asserts the bare forms with `typing_extensions.assert_type`. `.github/workflows/python.yml` runs `mypy --strict` on it in a step after the `Mypy` step. Reason: a default is a static property. pytest does not collect the file, because its name is not `test_*.py`, and the public API baseline does not render a bare annotation. The mypy step is the only check that fails when the default is removed. Verified 2026-11-15: removing the hub default, removing the protocol default, or setting the hub default to `Any` each makes `mypy --strict` fail on this file.
1. **Public API baseline unchanged.** `langs/python/api/vmx.api.txt` has no diff on Python 3.12. The base of `MessageHub` still renders `typing.Generic[~_THubMessage]`, and the protocol bases still render with their type variables. The baseline therefore does not guard the default, and decision 5 does.
1. **Runtime behavior unchanged.** `MessageHub` and the protocols change only in their type variables. Explicit parameterisations such as `MessageHub[Message]` keep their meaning. Existing annotations in the docs and the examples remain valid.
1. **ADR-0009 updated in place.** The `MessageHub` parameterisation row now says that a bare `MessageHub` means `MessageHub[Message]`. The row's Status line reads `clarified by ADR-0120, ADR-0121, ADR-0231`, and its registry cell reads `clarified by 0120, 0121, 0231`. Both use the list form that ADR-0009 already carried, with ADR-0231 added, as ADR README section 2.3 requires. Reason: the row is the cross-flavor record of this shape, and this ADR holds the reasons for the change.
1. **No conformance ID, spec chapter, HISTORY entry or version change.** The change is typing-only in the Python flavor. No `spec/NN-*.md` chapter changes, and the source version stays 3.30.0.
1. **Locks record the new dependency.** `langs/python/uv.lock` and four example locks (`examples/python`, `examples/python/textual/inspector`, `examples/python/textual/notes_showcase` and `examples/python/nicegui/notes_showcase`) record the `vmx` dependency on `typing-extensions` with the `>=4.12.0` specifier. Reason: each example installs `vmx` by path and records its dependency list, and `uv lock --locked` fails until the lock is updated. No pinned package version changes.
1. **CHANGELOG.** `langs/python/CHANGELOG.md` records the change under `### Changed` in the `[3.30.0] — unreleased source version` section (CONTRIBUTING section 4.3). The entry names the plain-mypy consequence in section 3.

## 3. Consequences

- Under `mypy --strict`, a bare `MessageHub()`, a bare `MessageHub` parameter and a bare `MessageHubProto` or `TransactionalMessageHubProto` annotation type-check as `Message` parameterisations. Consumers can drop the annotation.
- Under plain mypy (without `disallow_any_generics`), a bare annotation used to mean `Any` and accepted a hub of any message type. It now means `Message`. A parameter annotated bare rejects `MessageHub[MyMessage]` or a `MessageHubProto[MyMessage]` hub, and mypy reports `arg-type`. Verified 2026-11-15. The fix for such code is an explicit parameterisation, such as `MessageHub[Any]` or `MessageHub[MyMessage]`. Under `mypy --strict`, a bare annotation was already an error (`type-arg`), so strict code does not see the old acceptance.
- Under plain mypy, a bare `MessageHub()` assigned to an unannotated variable was already `var-annotated`. It now type-checks as `MessageHub[Message]`, and passing that variable where a `MessageHub[MyMessage]` is expected is an error.
- The Python package declares `typing-extensions>=4.12.0` as a new runtime dependency. Installing `vmx` upgrades a typing-extensions older than 4.12.0, and installs one where none is present.
- Each Python CI matrix cell runs one more `mypy --strict` step.
- The Swift and Rust hubs and the C# and TypeScript shapes are unchanged. The bare form exists only in Python, as ADR-0009 records.

## 4. Rejected alternatives

- **`typing.TypeVar` on Python 3.13 and later, `typing_extensions.TypeVar` below 3.13.** Two declarations for one contract, plus a conditional dependency marker. Rejected in favor of decision 2.
- **The issue's proposed floor, `typing-extensions>=4.4.0`.** Rejected: on Python 3.13, 4.4.0 and 4.5.0 fail at import, and 4.6.0 to 4.11.0 fail when a defaulted `TypeVar` is created (section 1).
- **The transitive copy from `reactivex`.** Rejected: `vmx` does not pin that copy, so it may be any release, including the releases that fail on Python 3.13.
- **`default=Any` or `default=object`.** Rejected: the bare forms would mean `MessageHub[Any]` or `MessageHub[object]`, not `Message`. The `Any` default fails the typing contract (decision 5, verified 2026-11-15).
- **Editing ADR-0009 alone, with no new ADR.** Issue #1903 proposed this. Rejected as the only record: the reasons for the default, the floor and the protocol choice need an ADR that ADR-0009 can link to. ADR-0009 keeps the row and gains the back-link.
