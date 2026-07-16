//
// HierarchicalVMBuilder<TModel, TVM> — immutable fluent builder for
// HierarchicalVM<TModel, TVM>.
//
// See spec/10-builders.md §3 and spec/18-hierarchical-vm.md (HIER-015/016/017).
//
// vmFactory decision (ADR-0061 §2.2):
// TypeScript requires a vmFactory because JS erases generic-type identity at
// runtime. Swift has reified generics but binds `TVM: AnyObject` (not
// `TVM: HierarchicalVM<TModel, TVM>`) because the self-referential constraint
// is rejected by the Swift compiler (see HierarchicalVM.swift file header).
// `AnyObject` exposes no `init(...)` surface, so this builder also cannot
// construct TVM directly and requires the same vmFactory pattern as TypeScript.
// The divergence is documented in ADR-0061 §2.2.
//
import Foundation

/// Immutable fluent builder for `HierarchicalVM<TModel, TVM>`.
///
/// Required fields, validated in this order at `build()`:
///   1. `model`
///   2. `childrenFactory`
///   3. `services` (hub + dispatcher)
///   4. `vmFactory`
///
/// Optional fields: `name` (default: `""` → resolved by `HierarchicalVM.init`
/// to `String(describing: TVM.self)`), `hint` (default: `""`),
/// `eagerChildren` (default: `false`).
///
/// Each setter returns a **new** builder instance; the original is unchanged
/// (BLD-001 / Swift struct copy semantics).
public struct HierarchicalVMBuilder<TModel, TVM: AnyObject> {

    // ── Stored state ─────────────────────────────────────────────────────

    private var _model: ModelBox?
    private var _childrenFactory: ((TVM) -> [TVM])?
    private var _hub: MessageHubProtocol?
    private var _dispatcher: Dispatcher?
    private var _name: String = ""
    private var _hint: String = ""
    private var _eagerChildren: Bool = false
    private var _vmFactory: ((TModel, @escaping (TVM) -> [TVM], MessageHubProtocol, Dispatcher, String, String, Bool) -> TVM)?

    /// One-shot box to distinguish "model was set (possibly to a TModel zero
    /// value)" from "model was never set" without `Hashable` constraints or
    /// sentinel values.
    private struct ModelBox { let value: TModel }

    // ── Init ─────────────────────────────────────────────────────────────

    public init() {}

    // ── Setters (copy-mutate-return) ─────────────────────────────────────

    /// Set the required domain model carried by each produced node.
    public func model(_ value: TModel) -> HierarchicalVMBuilder<TModel, TVM> {
        var c = self; c._model = ModelBox(value: value); return c
    }

    /// Set the required factory that produces the node's children given the
    /// (CRTP) parent node.
    public func childrenFactory(
        _ factory: @escaping (TVM) -> [TVM]
    ) -> HierarchicalVMBuilder<TModel, TVM> {
        var c = self; c._childrenFactory = factory; return c
    }

    /// Set the required message hub + dispatcher pair.
    public func services(
        hub: MessageHubProtocol, dispatcher: Dispatcher
    ) -> HierarchicalVMBuilder<TModel, TVM> {
        var c = self; c._hub = hub; c._dispatcher = dispatcher; return c
    }

    /// Set the optional node name (default: `""` → resolved by
    /// `HierarchicalVM.init` to `String(describing: TVM.self)`).
    public func name(_ value: String) -> HierarchicalVMBuilder<TModel, TVM> {
        var c = self; c._name = value; return c
    }

    /// Set the optional hint string (default: `""`).
    public func hint(_ value: String) -> HierarchicalVMBuilder<TModel, TVM> {
        var c = self; c._hint = value; return c
    }

    /// Set whether to eagerly materialize the child subtree at construct()
    /// time (default: `false`).
    public func eagerChildren(_ value: Bool) -> HierarchicalVMBuilder<TModel, TVM> {
        var c = self; c._eagerChildren = value; return c
    }

    /// Set the required factory that instantiates the concrete `TVM` subclass.
    ///
    /// Swift cannot call `TVM.init(...)` directly because `TVM` is bound to
    /// `AnyObject` (the self-referential constraint
    /// `TVM: HierarchicalVM<TModel, TVM>` is rejected by the Swift compiler;
    /// see `HierarchicalVM.swift`). Consumers supply a factory:
    ///
    /// ```swift
    /// .vmFactory { model, cf, hub, disp, name, hint, eager in
    ///     MyNode(model: model, childrenFactory: cf, hub: hub,
    ///            dispatcher: disp, name: name, hint: hint,
    ///            eagerChildren: eager)
    /// }
    /// ```
    ///
    /// The `@escaping` attribute on the `cf` parameter within the setter type
    /// allows passing `cf` to `HierarchicalVM.init(childrenFactory:)` which
    /// requires an `@escaping` closure.
    public func vmFactory(
        _ factory: @escaping (TModel, @escaping (TVM) -> [TVM], MessageHubProtocol, Dispatcher, String, String, Bool) -> TVM
    ) -> HierarchicalVMBuilder<TModel, TVM> {
        var c = self; c._vmFactory = factory; return c
    }

    /// Wire a fresh `MessageHub` + `ImmediateDispatcher.INSTANCE` as the
    /// default services pair. Mirrors `withDefaultServices()` in TypeScript /
    /// Python (ADR-0035 §2 H2).
    public func withDefaultServices() -> HierarchicalVMBuilder<TModel, TVM> {
        services(hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE)
    }

    // ── build() ──────────────────────────────────────────────────────────

    /// Validate all required fields and construct a `TVM` node.
    ///
    /// Validation order: `model` → `childrenFactory` → `services` →
    /// `vmFactory`. The first missing field causes a `BuilderValidationError`.
    ///
    /// - Throws: `BuilderValidationError(missingField:)` naming the first
    ///   missing required field.
    /// - Returns: A freshly constructed `TVM` node with the builder's settled
    ///   configuration. Calling `build()` again produces an independent
    ///   instance sharing equivalent configuration (HIER-016).
    public func build() throws -> TVM {
        guard let box = _model else {
            throw BuilderValidationError(missingField: "model")
        }
        guard let childrenFactory = _childrenFactory else {
            throw BuilderValidationError(missingField: "childrenFactory")
        }
        guard let hub = _hub, let dispatcher = _dispatcher else {
            throw BuilderValidationError(missingField: "services")
        }
        guard let vmFactory = _vmFactory else {
            throw BuilderValidationError(missingField: "vmFactory")
        }
        return vmFactory(
            box.value,
            childrenFactory,
            hub,
            dispatcher,
            _name,
            _hint,
            _eagerChildren
        )
    }
}

// ── HierarchicalVM entry point ────────────────────────────────────────────────

extension HierarchicalVM {
    /// Entry point for the immutable fluent builder.
    ///
    /// ```swift
    /// let node = try HierarchicalVM<String, MyNode>.builder()
    ///     .model("root")
    ///     .childrenFactory { _ in [] }
    ///     .withDefaultServices()
    ///     .vmFactory { model, cf, hub, disp, name, hint, eager in
    ///         MyNode(model: model, childrenFactory: cf, hub: hub,
    ///                dispatcher: disp, name: name, hint: hint,
    ///                eagerChildren: eager)
    ///     }
    ///     .build()
    /// ```
    public static func builder() -> HierarchicalVMBuilder<TModel, TVM> {
        HierarchicalVMBuilder<TModel, TVM>()
    }
}
