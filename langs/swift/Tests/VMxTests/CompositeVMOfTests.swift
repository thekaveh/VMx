//
// CompositeVMOf conformance tests.
//
// Claimed IDs: COMP-007 (modeled composite maps model factory to children).
//
// NOTE: `swift test` cannot run on a CommandLineTools-only host (no XCTest
// module); this target is CI-verified only (`swift.yml` on macos-latest).
//
import XCTest
@testable import VMx

final class CompositeVMOfTests: XCTestCase {

    private struct TestModel: Equatable {
        let id: Int
    }

    /// COMP-007 — Modeled composite maps model factory output to children.
    func testComp007ModeledCompositeChildren() throws {
        let m1 = TestModel(id: 1)
        let m2 = TestModel(id: 2)

        let composite = try CompositeVMOf<TestModel, ComponentVMOf<TestModel>>.builder()
            .name("composite")
            .withNullServices()
            .childrenModels { [m1, m2] }
            .childModelToChildViewModel { model in
                try! ComponentVMOf<TestModel>.builder()
                    .name("vm-\(model.id)")
                    .model(model)
                    .withNullServices()
                    .build()
            }
            .build()

        try composite.construct()

        XCTAssertEqual(composite.count, 2)
        XCTAssertEqual(composite.at(0).model, m1)
        XCTAssertEqual(composite.at(1).model, m2)
    }
}
