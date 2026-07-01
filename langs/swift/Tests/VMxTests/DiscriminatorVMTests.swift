import XCTest
import Combine
@testable import VMx

final class DiscriminatorVMTests: XCTestCase {
    private var cancellables: Set<AnyCancellable> = []

    override func tearDown() {
        cancellables.removeAll()
        super.tearDown()
    }

    /// DISC-001 — initial active key and isActive.
    func testDISC001InitialActiveKeyAndIsActive() {
        let sut = DiscriminatorVM(initial: "nav")
        XCTAssertEqual(sut.activeKey, "nav")
        XCTAssertTrue(sut.isActive("nav"))
        XCTAssertFalse(sut.isActive("modal"))
    }

    /// DISC-002 — setActiveKey emits change.
    func testDISC002SetActiveKeyEmitsChange() {
        let sut = DiscriminatorVM(initial: "nav")
        var seen: [String] = []
        sut.activeChanged.sink { seen.append($0) }.store(in: &cancellables)
        sut.setActiveKey("detail")
        XCTAssertEqual(sut.activeKey, "detail")
        XCTAssertEqual(seen, ["detail"])
    }

    /// DISC-003 — setting same key is a no-op.
    func testDISC003SettingSameKeyIsNoop() {
        let sut = DiscriminatorVM(initial: "nav")
        var seen: [String] = []
        sut.activeChanged.sink { seen.append($0) }.store(in: &cancellables)
        sut.setActiveKey("nav")
        XCTAssertTrue(seen.isEmpty)
    }

    /// DISC-004 — modalOpen activates modal key.
    func testDISC004ModalOpenActivatesModalKey() {
        let sut = DiscriminatorVM(initial: "nav")
        sut.modalOpen("modal")
        XCTAssertEqual(sut.activeKey, "modal")
        XCTAssertTrue(sut.isActive("modal"))
    }

    /// DISC-005 — modalClose restores prior key.
    func testDISC005ModalCloseRestoresPriorKey() {
        let sut = DiscriminatorVM(initial: "nav")
        sut.setActiveKey("detail")
        sut.modalOpen("modal")
        sut.modalClose()
        XCTAssertEqual(sut.activeKey, "detail")
    }

    /// DISC-006 — nested modal precedence restores in LIFO order.
    func testDISC006NestedModalPrecedenceRestoresInLifoOrder() {
        let sut = DiscriminatorVM(initial: "nav")
        sut.modalOpen("modal-a")
        sut.modalOpen("modal-b")
        sut.modalClose()
        XCTAssertEqual(sut.activeKey, "modal-a")
        sut.modalClose()
        XCTAssertEqual(sut.activeKey, "nav")
    }
}
