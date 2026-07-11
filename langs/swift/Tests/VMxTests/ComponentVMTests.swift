//
// ComponentVM conformance tests.
//
// Claimed IDs: CVM-001..009 (CVM-003's "no setter" is compiler-shaped in
// Swift — external writes trap per ADR-0037; the test verifies the
// readonly builder and internal update path).
//
import XCTest
import Combine
@testable import VMx

private struct Tab: Equatable {
    let title: String
}

/// Non-`Equatable` *reference* (class) model — exercises the
/// reference-identity default suppression (VMX-005).
private final class RefModel {
    let n: Int
    init(_ n: Int) { self.n = n }
}

private final class NotificationProbeVM: ComponentVMBase {
    private var storedValue = 0

    var value: Int {
        get { storedValue }
        set {
            guard storedValue != newValue else { return }
            storedValue = newValue
            _notifyPropertyChanged("value")
        }
    }

    func emitValueNotification() {
        _notifyPropertyChanged("value")
    }
}

final class ComponentVMTests: XCTestCase {

    /// CVM-001 — Construct emits ConstructionStatusChangedMessage(Constructed).
    func testCvm001ConstructEmitsStatusMessage() throws {
        let hub = MessageHub()
        let vm = try ComponentVM.builder()
            .name("c")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()
        var seen: [ConstructionStatus] = []
        let cancel = hub.messages
            .compactMap { ($0 as? ConstructionStatusChangedMessage)?.status }
            .sink { seen.append($0) }

        try vm.construct()

        // Catalog CVM-001: exactly [Constructing, Constructed] in order, and the
        // VM reports isConstructed (not merely "contains Constructed").
        XCTAssertEqual(seen, [.constructing, .constructed])
        XCTAssertTrue(vm.isConstructed)
        cancel.cancel()
    }

    /// CVM-002 — Modeled component fires PropertyChanged("model") on set
    /// (camelCase per the Swift idiom, spec/04 §4 / ADR-0006).
    func testCvm002ModelChangePublishes() throws {
        let hub = MessageHub()
        let vm = try ComponentVMOf<Tab>.builder()
            .name("tab")
            .model(Tab(title: "home"))
            .modelEquals(==)
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()
        var seen: [String] = []
        let cancel = hub.messages
            .compactMap { ($0 as? PropertyChangedMessage)?.propertyName }
            .sink { seen.append($0) }

        vm.model = Tab(title: "settings")

        XCTAssertTrue(seen.contains("model"))
        cancel.cancel()
    }

    /// CVM-003 — ReadonlyComponentVM exposes no usable Model setter.
    /// Swift cannot remove the inherited setter, so external writes trap
    /// (ADR-0037); this verifies the dedicated readonly builder
    /// (`ReadonlyComponentVMOfBuilder<Model>()` — the direct entry, since a
    /// static `builder()` shadow is ambiguous/inexpressible in Swift)
    /// produces the readonly type and internal updates flow via `_setModel`.
    func testCvm003ReadonlyBuilderProducesReadonlyVM() throws {
        let vm = try ReadonlyComponentVMOfBuilder<Tab>()
            .name("r")
            .model(Tab(title: "fixed"))
            .withNullServices()
            .build()
        XCTAssertEqual(vm.type, .readOnlyComponent)
        XCTAssertEqual(vm.model.title, "fixed")

        vm._setModel(Tab(title: "service-updated")) // @testable internal path
        XCTAssertEqual(vm.model.title, "service-updated")
    }

    /// CVM-004 — `modeledHint` is recomputed when the model changes AND a
    /// PropertyChangedMessage("modeledHint") is emitted on the hub (both catalog
    /// clauses; the prior test built with null services so the hub clause was
    /// unobservable).
    func testCvm004ModeledHintRecomputed() throws {
        let hub = MessageHub()
        let vm = try ComponentVMOf<Tab>.builder()
            .name("tab")
            .model(Tab(title: "home"))
            .modeledHinter { $0.title.uppercased() }
            .modelEquals(==)
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()
        XCTAssertEqual(vm.modeledHint, "HOME")

        var hintMessages: [String] = []
        let cancel = hub.messages
            .compactMap { msg -> String? in
                guard let pcm = msg as? PropertyChangedMessage, pcm.sender === vm,
                      pcm.propertyName == "modeledHint" else { return nil }
                return pcm.propertyName
            }
            .sink { hintMessages.append($0) }

        vm.model = Tab(title: "settings")

        XCTAssertEqual(vm.modeledHint, "SETTINGS")
        XCTAssertEqual(hintMessages.count, 1,
            "exactly one PropertyChangedMessage(modeledHint) on model change")
        cancel.cancel()
    }

    /// CVM-005 — Name and Hint are immutable post-construction. In Swift
    /// immutability is compiler-enforced (`let`); this asserts the values
    /// land and survive a lifecycle cycle.
    func testCvm005IdentityProperties() throws {
        let vm = try ComponentVM.builder()
            .name("hello")
            .hint("greeting")
            .withNullServices()
            .build()
        XCTAssertEqual(vm.name, "hello")
        XCTAssertEqual(vm.hint, "greeting")
        XCTAssertEqual(vm.type, .component)
        XCTAssertEqual(vm.status, .destructed)

        try vm.construct()
        XCTAssertEqual(vm.name, "hello")
        XCTAssertEqual(vm.hint, "greeting")
    }

    /// CVM-006 — SelectCommand can_execute reflects selection state.
    func testCvm006SelectCommandReflectsSelectionState() throws {
        let hub = MessageHub()
        let child = try ComponentVM.builder()
            .name("child")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()
        let comp = try CompositeVM<ComponentVM>.builder()
            .name("c")
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [child] }
            .build()
        try comp.construct()

        XCTAssertTrue(child.selectCommand.canExecute(), "constructed and not current")

        child.selectCommand.execute()

        XCTAssertTrue(comp.current === child)
        XCTAssertFalse(child.selectCommand.canExecute(), "already current")
        XCTAssertTrue(child.deselectCommand.canExecute())
    }

    /// CVM-007 — helper emits one hub notification before one local notification.
    func testCvm007NotificationHelperEmitsHubThenLocalOnce() {
        let hub = MessageHub()
        let vm = NotificationProbeVM(
            name: "probe", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
        )
        var trace: [String] = []
        let hubCancel = hub.messages.sink { message in
            if let change = message as? PropertyChangedMessage,
               change.propertyName == "value" {
                trace.append("hub:\(vm.value)")
            }
        }
        let localCancel = vm.propertyChanged.sink { name in
            trace.append("local:\(name):\(vm.value)")
        }

        vm.value = 7

        XCTAssertEqual(trace, ["hub:7", "local:value:7"])
        hubCancel.cancel()
        localCancel.cancel()
    }

    /// CVM-007 — deferred delivery and re-entrant disposal preserve the pair.
    func testCvm007DeferredDeliveryAndReentrantDisposalCompletePair() throws {
        let batchedHub = MessageHub()
        let batchedVM = NotificationProbeVM(
            name: "batched", hub: batchedHub, dispatcher: ImmediateDispatcher.INSTANCE
        )
        var batchedTrace: [String] = []
        let batchedHubCancel = batchedHub.messages.sink { message in
            if let change = message as? PropertyChangedMessage,
               change.propertyName == "value" {
                batchedTrace.append("hub")
            }
        }
        let batchedLocalCancel = batchedVM.propertyChanged.sink { name in
            if name == "value" { batchedTrace.append("local") }
        }

        try batchedHub.batch { batchedVM.value = 7 }

        XCTAssertEqual(batchedTrace, ["local", "hub"])
        batchedHubCancel.cancel()
        batchedLocalCancel.cancel()

        let disposingHub = MessageHub()
        let disposingVM = NotificationProbeVM(
            name: "disposing", hub: disposingHub, dispatcher: ImmediateDispatcher.INSTANCE
        )
        var disposingTrace: [String] = []
        let disposingHubCancel = disposingHub.messages.sink { message in
            if let change = message as? PropertyChangedMessage,
               change.propertyName == "value" {
                disposingTrace.append("hub")
                disposingVM.dispose()
            }
        }
        let disposingLocalCancel = disposingVM.propertyChanged.sink { name in
            if name == "value" { disposingTrace.append("local") }
        }

        disposingVM.value = 7

        XCTAssertEqual(disposingTrace, ["hub", "local"])
        disposingHubCancel.cancel()
        disposingLocalCancel.cancel()
    }

    /// CVM-008 — the setter's equality guard suppresses both channels.
    func testCvm008EqualityGuardSuppressesBothChannels() {
        let hub = MessageHub()
        let vm = NotificationProbeVM(
            name: "probe", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
        )
        var hubNames: [String] = []
        var localNames: [String] = []
        let hubCancel = hub.messages
            .compactMap { ($0 as? PropertyChangedMessage)?.propertyName }
            .sink { hubNames.append($0) }
        let localCancel = vm.propertyChanged.sink { localNames.append($0) }

        vm.value = 7
        vm.value = 7

        XCTAssertEqual(hubNames, ["value"])
        XCTAssertEqual(localNames, ["value"])
        hubCancel.cancel()
        localCancel.cancel()
    }

    /// CVM-009 — helper calls after disposal are silent on both channels.
    func testCvm009NotificationHelperIsInertAfterDisposal() {
        let hub = MessageHub()
        let vm = NotificationProbeVM(
            name: "probe", hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
        )
        var hubNames: [String] = []
        var localNames: [String] = []
        let hubCancel = hub.messages
            .compactMap { ($0 as? PropertyChangedMessage)?.propertyName }
            .sink { hubNames.append($0) }
        let localCancel = vm.propertyChanged.sink { localNames.append($0) }
        vm.dispose()
        hubNames.removeAll()
        localNames.removeAll()

        vm.emitValueNotification()

        XCTAssertEqual(hubNames, [])
        XCTAssertEqual(localNames, [])
        hubCancel.cancel()
        localCancel.cancel()
    }

    /// Modeled component starts with its initial model.
    func testModeledInitialModel() throws {
        let vm = try ComponentVMOf<Tab>.builder()
            .name("tab")
            .model(Tab(title: "home"))
            .withNullServices()
            .build()
        XCTAssertEqual(vm.model.title, "home")
    }

    /// Setting `model` to an equal value does NOT publish
    /// (spec/05 §3 rule 1, with an explicit equality predicate).
    func testModelEqualSetIsNoOp() throws {
        let hub = MessageHub()
        let vm = try ComponentVMOf<Tab>.builder()
            .name("tab")
            .model(Tab(title: "home"))
            .modelEquals(==)
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()
        var seen: [String] = []
        let cancel = hub.messages
            .compactMap { ($0 as? PropertyChangedMessage)?.propertyName }
            .sink { seen.append($0) }

        vm.model = Tab(title: "home")

        XCTAssertFalse(seen.contains("model"))
        cancel.cancel()
    }

    /// Equatable models default to `==` via the builder — no explicit
    /// `.modelEquals` needed (regression: the builder previously fell back
    /// to an always-false predicate despite the documented default).
    func testEquatableBuilderDefaultsToEquality() throws {
        let hub = MessageHub()
        let vm = try ComponentVMOf<Tab>.builder()
            .name("tab")
            .model(Tab(title: "home"))
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()
        var seen: [String] = []
        let cancel = hub.messages
            .compactMap { ($0 as? PropertyChangedMessage)?.propertyName }
            .sink { seen.append($0) }

        vm.model = Tab(title: "home") // equal — suppressed by the == default
        XCTAssertFalse(seen.contains("model"))

        vm.model = Tab(title: "settings") // different — fires
        XCTAssertTrue(seen.contains("model"))
        cancel.cancel()
    }

    /// `propertyChanged` (in-process publisher) emits property names on
    /// model change.
    func testPropertyChangedPublisherFires() throws {
        let vm = try ComponentVMOf<Tab>.builder()
            .name("tab")
            .model(Tab(title: "home"))
            .modelEquals(==)
            .withNullServices()
            .build()
        var seen: [String] = []
        let cancel = vm.propertyChanged.sink { seen.append($0) }
        vm.model = Tab(title: "next")
        XCTAssertTrue(seen.contains("model"))
        cancel.cancel()
    }

    /// Builder `onModelChanged` callback fires on model set (path no test,
    /// example, or doc exercised).
    func testBuilderOnModelChangedFires() throws {
        var seen: [Tab] = []
        let vm = try ComponentVMOf<Tab>.builder()
            .name("tab")
            .model(Tab(title: "home"))
            .onModelChanged { seen.append($0) }
            .withNullServices()
            .build()

        vm.model = Tab(title: "settings")

        XCTAssertEqual(seen.map(\.title), ["settings"])
    }

    /// VMX-005 — a non-`Equatable` *class* model suppresses a re-publish when
    /// set to the *same instance* (HUB-005 idempotent-set via reference
    /// identity, parity with C#/Py/TS); a different instance still publishes.
    /// Previously the non-Equatable default was a constant-`false` predicate,
    /// so every set — including the same instance — published.
    func testNonEquatableClassModelSuppressesIdentitySet() throws {
        let hub = MessageHub()
        let first = RefModel(1)
        let vm = try ComponentVMOf<RefModel>.builder()
            .name("ref")
            .model(first)
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()
        var seen: [String] = []
        let cancel = hub.messages
            .compactMap { ($0 as? PropertyChangedMessage)?.propertyName }
            .sink { seen.append($0) }

        vm.model = first            // same instance — suppressed (HUB-005)
        XCTAssertFalse(seen.contains("model"), "identity-equal set must not publish")

        vm.model = RefModel(2)      // different instance — publishes
        XCTAssertTrue(seen.contains("model"), "a different instance must publish")
        cancel.cancel()
    }

    /// VMX-100 — `ReadonlyComponentVMOf.readonlyBuilder()` is the distinctly
    /// named, correctly-typed entry point: it produces a read-only VM (the
    /// inherited static `builder()` would produce a *writable* `ComponentVMOf`).
    func testReadonlyBuilderEntryPointProducesReadonlyVM() throws {
        let vm = try ReadonlyComponentVMOf<Tab>.readonlyBuilder()
            .name("r")
            .model(Tab(title: "fixed"))
            .withNullServices()
            .build()
        XCTAssertEqual(vm.type, .readOnlyComponent)
        XCTAssertEqual(vm.model.title, "fixed")
    }

    /// ADR-0091 — after dispose, setting `model` preserves the retained model
    /// and publishes nothing further.
    func testDisposedModelSetIsInert() throws {
        let hub = MessageHub()
        let vm = try ComponentVMOf<Tab>.builder()
            .name("tab")
            .model(Tab(title: "home"))
            .modelEquals(==)
            .services(hub: hub, dispatcher: ImmediateDispatcher.INSTANCE)
            .build()
        vm.dispose()

        var seen: [String] = []
        let cancel = hub.messages
            .compactMap { ($0 as? PropertyChangedMessage)?.propertyName }
            .sink { seen.append($0) }

        vm.model = Tab(title: "after-dispose")

        XCTAssertEqual(vm.model.title, "home", "disposed model remains terminal")
        XCTAssertFalse(seen.contains("model"), "disposed VM publishes nothing")
        cancel.cancel()
    }
}
