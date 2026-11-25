//
// API tests for consumer subclasses of `ComponentVMOf` whose model is
// `Equatable` (issue #1600). The file imports VMx without @testable, so the
// subclasses use the public API only (ADR-0066), as
// `ChildTransitionHelperAPITests.swift` does. Each subclass initializer calls
// `super.init` without `modelEquals`: the `==` default must come from the
// initializer that the subclass reaches, not from the caller.
//
// No conformance-ID markers: the equality rule is spec/05 §3 (HUB-005), which
// the builder path is already covered for in `ComponentVMTests`.
//
import XCTest
import Combine
import VMx

private struct Draft: Equatable {
    var title: String
}

/// A consumer subclass with a stored property. Its initializer calls
/// `super.init` without a `modelEquals` argument.
private final class DraftVM: ComponentVMOf<Draft> {
    let revision: Int

    init(hub: MessageHubProtocol) {
        revision = 1
        super.init(
            name: "draft", initialModel: Draft(title: "a"),
            hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
        )
    }
}

/// A consumer subclass without a stored property. Its initializer calls
/// `super.init` without a `modelEquals` argument.
private final class PlainDraftVM: ComponentVMOf<Draft> {
    init(hub: MessageHubProtocol) {
        super.init(
            name: "plain", initialModel: Draft(title: "a"),
            hub: hub, dispatcher: ImmediateDispatcher.INSTANCE
        )
    }
}

final class ComponentVMOfSubclassAPITests: XCTestCase {
    func testStoredPropertySubclassSuppressesEqualAssignment() {
        let vm = DraftVM(hub: MessageHub())
        var seen: [String] = []
        let cancel = vm.propertyChanged.sink { seen.append($0) }
        defer { cancel.cancel() }

        vm.model = Draft(title: "a") // equal: the == default suppresses it
        XCTAssertFalse(seen.contains("model"))

        vm.model = Draft(title: "b") // different: publishes once
        XCTAssertEqual(seen.filter { $0 == "model" }.count, 1)
    }

    func testPlainSubclassSuppressesEqualAssignment() {
        let vm = PlainDraftVM(hub: MessageHub())
        var seen: [String] = []
        let cancel = vm.propertyChanged.sink { seen.append($0) }
        defer { cancel.cancel() }

        vm.model = Draft(title: "a") // equal: the == default suppresses it
        XCTAssertFalse(seen.contains("model"))

        vm.model = Draft(title: "b") // different: publishes once
        XCTAssertEqual(seen.filter { $0 == "model" }.count, 1)
    }
}
