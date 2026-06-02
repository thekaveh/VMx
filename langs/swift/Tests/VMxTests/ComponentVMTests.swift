//
// ComponentVM conformance subset (CVM-001..CVM-006).
//
import XCTest
import Combine
@testable import VMx

private struct Tab: Equatable {
    let title: String
}

final class ComponentVMTests: XCTestCase {

    /// CVM-001 — ComponentVM has the baseline identity properties.
    func testCvm001IdentityProperties() throws {
        let vm = try ComponentVM.builder()
            .name("hello")
            .hint("greeting")
            .withNullServices()
            .build()
        XCTAssertEqual(vm.name, "hello")
        XCTAssertEqual(vm.hint, "greeting")
        XCTAssertEqual(vm.type, .component)
        XCTAssertEqual(vm.status, .destructed)
    }

    /// CVM-002 — ComponentVMOf starts with its initial model.
    func testCvm002ModeledInitialModel() throws {
        let vm = try ComponentVMOf<Tab>.builder()
            .name("tab")
            .model(Tab(title: "home"))
            .withNullServices()
            .build()
        XCTAssertEqual(vm.model.title, "home")
    }

    /// CVM-003 — Setting `model` publishes a PropertyChangedMessage.
    func testCvm003ModelChangePublishes() throws {
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

        XCTAssertTrue(seen.contains("Model"))
        cancel.cancel()
    }

    /// CVM-004 — Setting `model` to an equal value does NOT publish
    /// (when an equality predicate is supplied).
    func testCvm004ModelEqualSetIsNoOp() throws {
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

        XCTAssertFalse(seen.contains("Model"))
        cancel.cancel()
    }

    /// CVM-005 — `modeledHint` is recomputed from the configured hinter.
    func testCvm005ModeledHintRecomputed() throws {
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

    /// CVM-006 — `propertyChanged` publisher emits property names on
    /// model change.
    func testCvm006PropertyChangedPublisherFires() throws {
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
}
