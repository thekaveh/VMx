//
// PostDisposeContainerMembershipTests — composite and group membership and
// selection after disposal, as the disposal contract's Swift exception states
// (#1319). `add` asserts in a debug build, so these tests use `addResult`,
// which reports the same refusal as a value.
//
import XCTest
@testable import VMx

final class PostDisposeContainerMembershipTests: XCTestCase {

    private func disposedComposite() throws -> (CompositeVM<ComponentVM>, ComponentVM, ComponentVM) {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let a = try ComponentVM.builder().name("a").services(hub: hub, dispatcher: dispatcher).build()
        let b = try ComponentVM.builder().name("b").services(hub: hub, dispatcher: dispatcher).build()
        let composite = try CompositeVM<ComponentVM>.builder()
            .name("p").services(hub: hub, dispatcher: dispatcher)
            .children { [a, b] }.build()
        try composite.construct()
        try composite.setCurrent(a)
        composite.dispose()
        return (composite, a, b)
    }

    private func extra() throws -> ComponentVM {
        try ComponentVM.builder()
            .name("x").services(hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE).build()
    }

    func testDisposedCompositeSelectionOfAMemberOrNilIsInert() throws {
        let (composite, a, b) = try disposedComposite()

        composite.current = b
        XCTAssertTrue(composite.current === a)
        XCTAssertNoThrow(try composite.setCurrent(b))
        XCTAssertTrue(composite.current === a)

        composite.current = nil
        XCTAssertTrue(composite.current === a)
        XCTAssertNoThrow(try composite.setCurrent(nil))
        XCTAssertTrue(composite.current === a)
    }

    func testDisposedCompositeStillRefusesANonMember() throws {
        let (composite, a, _) = try disposedComposite()

        XCTAssertFalse(composite.canSetCurrent(try extra()))
        XCTAssertThrowsError(try composite.setCurrent(try extra())) { error in
            XCTAssertTrue(error is CompositeMembershipError)
        }
        XCTAssertTrue(composite.current === a)
    }

    func testDisposedCompositeRefusesInsertAndReplace() throws {
        let (composite, a, b) = try disposedComposite()

        guard case .failure(.attachmentFailed) = composite.insertResult(try extra(), at: 0) else {
            return XCTFail("insertResult after disposal must fail")
        }
        guard case .failure(.attachmentFailed) = composite.replaceResult(at: 1, with: try extra()) else {
            return XCTFail("replaceResult after disposal must fail")
        }
        composite.insert(try extra(), at: 0)
        composite.replace(at: 1, with: try extra())

        XCTAssertEqual(composite.count, 2)
        XCTAssertTrue(composite.snapshot()[0] === a)
        XCTAssertTrue(composite.snapshot()[1] === b)
        XCTAssertTrue(composite.current === a)
    }

    func testDisposedCompositeRefusesAddAndMoveAndIgnoresRemoveAndClear() throws {
        let (composite, a, b) = try disposedComposite()

        guard case .failure(.attachmentFailed) = composite.addResult(try extra()) else {
            return XCTFail("addResult after disposal must fail")
        }
        XCTAssertThrowsError(try composite.move(from: 0, to: 1))
        XCTAssertFalse(composite.remove(b))
        composite.removeAt(0)
        composite.clear()

        XCTAssertEqual(composite.count, 2)
        XCTAssertTrue(composite.current === a)
    }

    func testDisposedGroupRefusesAddAndIgnoresRemoveAndClear() throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let a = try ComponentVM.builder().name("a").services(hub: hub, dispatcher: dispatcher).build()
        let group = try GroupVM<ComponentVM>.builder()
            .name("g").services(hub: hub, dispatcher: dispatcher)
            .children { [a] }.build()
        try group.construct()
        group.dispose()

        guard case .failure(.attachmentFailed) = group.addResult(try extra()) else {
            return XCTFail("addResult after disposal must fail")
        }
        XCTAssertFalse(group.remove(a))
        group.clear()
        XCTAssertEqual(group.count, 1)
    }

    func testDisposedGroupRefusesInsertReplaceAndMoveAndIgnoresRemoveAt() throws {
        let hub = MessageHub()
        let dispatcher = ImmediateDispatcher.INSTANCE
        let a = try ComponentVM.builder().name("a").services(hub: hub, dispatcher: dispatcher).build()
        let b = try ComponentVM.builder().name("b").services(hub: hub, dispatcher: dispatcher).build()
        let group = try GroupVM<ComponentVM>.builder()
            .name("g").services(hub: hub, dispatcher: dispatcher)
            .children { [a, b] }.build()
        try group.construct()
        group.dispose()

        guard case .failure(.attachmentFailed) = group.insertResult(try extra(), at: 0) else {
            return XCTFail("insertResult after disposal must fail")
        }
        guard case .failure(.attachmentFailed) = group.replaceResult(at: 1, with: try extra()) else {
            return XCTFail("replaceResult after disposal must fail")
        }
        group.insert(try extra(), at: 0)
        group.replace(at: 1, with: try extra())
        XCTAssertThrowsError(try group.move(from: 0, to: 1))
        group.removeAt(0)

        XCTAssertEqual(group.count, 2)
        XCTAssertTrue(group.snapshot()[0] === a)
        XCTAssertTrue(group.snapshot()[1] === b)
    }
}
