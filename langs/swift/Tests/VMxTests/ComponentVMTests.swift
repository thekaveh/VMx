//
// ComponentVM conformance tests.
//
// Claimed IDs: CVM-001..006 (CVM-003's "no setter" is compiler-shaped in
// Swift — external writes trap per ADR-0037; the test verifies the
// readonly builder and internal update path).
//
import XCTest
import Combine
@testable import VMx

private struct Tab: Equatable {
    let title: String
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

        vm.construct()

        XCTAssertTrue(seen.contains(.constructed))
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
    /// (ADR-0037); this verifies the dedicated readonly builder produces
    /// the readonly type and internal updates flow through `_setModel`.
    func testCvm003ReadonlyBuilderProducesReadonlyVM() throws {
        let vm = try ReadonlyComponentVMOf<Tab>.builder()
            .name("r")
            .model(Tab(title: "fixed"))
            .withNullServices()
            .build()
        XCTAssertEqual(vm.type, .readOnlyComponent)
        XCTAssertEqual(vm.model.title, "fixed")

        vm._setModel(Tab(title: "service-updated")) // @testable internal path
        XCTAssertEqual(vm.model.title, "service-updated")
    }

    /// CVM-004 — `modeledHint` is recomputed when the model changes.
    func testCvm004ModeledHintRecomputed() throws {
        let vm = try ComponentVMOf<Tab>.builder()
            .name("tab")
            .model(Tab(title: "home"))
            .modeledHinter { $0.title.uppercased() }
            .modelEquals(==)
            .withNullServices()
            .build()
        XCTAssertEqual(vm.modeledHint, "HOME")
        vm.model = Tab(title: "settings")
        XCTAssertEqual(vm.modeledHint, "SETTINGS")
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

        vm.construct()
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
        comp.construct()

        XCTAssertTrue(child.selectCommand.canExecute(), "constructed and not current")

        child.selectCommand.execute()

        XCTAssertTrue(comp.current === child)
        XCTAssertFalse(child.selectCommand.canExecute(), "already current")
        XCTAssertTrue(child.deselectCommand.canExecute())
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
}
