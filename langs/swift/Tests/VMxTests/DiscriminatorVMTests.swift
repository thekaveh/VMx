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

    /// DISC-007 — modalDepth tracks frames and disposal releases them.
    func testDISC007ModalDepthTracksFramesAndDisposalReleasesThem() {
        let sut = DiscriminatorVM(initial: "nav")
        XCTAssertEqual(sut.modalDepth, 0)
        sut.modalOpen("modal-a")
        XCTAssertEqual(sut.modalDepth, 1)
        sut.modalOpen("modal-b")
        XCTAssertEqual(sut.modalDepth, 2)
        sut.modalClose()
        XCTAssertEqual(sut.modalDepth, 1)
        sut.dispose()
        XCTAssertEqual(sut.modalDepth, 0)
    }

    /// DISC-008 — clearModals drains without changing the active key.
    func testDISC008ClearModalsDrainsWithoutChangingActiveKey() {
        let sut = DiscriminatorVM(initial: "nav")
        sut.modalOpen("modal-a")
        sut.modalOpen("modal-b")
        var seen: [String] = []
        sut.activeChanged.sink { seen.append($0) }.store(in: &cancellables)

        sut.clearModals()

        XCTAssertEqual(sut.modalDepth, 0)
        XCTAssertEqual(sut.activeKey, "modal-b")
        XCTAssertTrue(seen.isEmpty)
        sut.modalClose()
        XCTAssertEqual(sut.activeKey, "modal-b")
    }

    /// DISC-009 — non-modal set abandons history including for the active key.
    func testDISC009NonModalSetAbandonsHistoryIncludingSameKey() {
        let sut = DiscriminatorVM(initial: "nav")
        var seen: [String] = []
        sut.activeChanged.sink { seen.append($0) }.store(in: &cancellables)
        sut.modalOpen("modal-a")
        sut.modalOpen("modal-b")

        sut.setActiveKey("route")

        XCTAssertEqual(sut.modalDepth, 0)
        sut.modalClose()
        XCTAssertEqual(sut.activeKey, "route")

        sut.modalOpen("modal")
        let changeCount = seen.count
        sut.setActiveKey("modal")
        XCTAssertEqual(sut.modalDepth, 0)
        XCTAssertEqual(seen.count, changeCount)
    }
}
