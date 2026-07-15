import XCTest
@testable import VMx

final class ModalPresentationTests: XCTestCase {
    /// DIA-009 — present returns modal result.
    func testDIA009PresentReturnsModalResult() async {
        let modal = BasicModalVM(cancellationResult: "cancel")
        let service = HostDialogService()

        let result = await service.present(modal)

        XCTAssertEqual(result, "accepted")
        XCTAssertEqual(modal.result, "accepted")
    }

    /// DIA-010 — null present uses cancellation result.
    func testDIA010NullPresentUsesCancellationResult() async {
        let modal = BasicModalVM(cancellationResult: "cancel")

        let result = await NullDialogService.INSTANCE.present(modal)

        XCTAssertEqual(result, "cancel")
        XCTAssertTrue(modal.isDismissed)
        XCTAssertEqual(modal.result, "cancel")
    }

    /// DIA-011 — modal dispose completes with cancellation result.
    func testDIA011ModalDisposeCompletesWithCancellationResult() async {
        let modal = BasicModalVM(cancellationResult: "cancel")

        modal.dispose()

        let result = await modal.waitResult()
        XCTAssertEqual(result, "cancel")
        XCTAssertTrue(modal.isDismissed)
    }

    /// DIA-012 — modal dismiss is idempotent.
    func testDIA012ModalDismissIsIdempotent() async {
        let modal = BasicModalVM(cancellationResult: "cancel")

        modal.dismiss("first")
        modal.dismiss("second")

        let result = await modal.waitResult()
        XCTAssertEqual(result, "first")
        XCTAssertEqual(modal.result, "first")
    }

    func testConcurrentWaitRegistrationAndDismissalIsAtomic() async {
        let modal = BasicModalVM(cancellationResult: -1)
        let resumed = expectation(description: "every modal waiter resumed")
        resumed.expectedFulfillmentCount = 64
        let dismissalsReturned = expectation(description: "all dismissals returned")
        let results = LockedModalResults()

        for _ in 0..<64 {
            Task {
                results.append(await modal.waitResult())
                resumed.fulfill()
            }
        }
        DispatchQueue.global().async {
            DispatchQueue.concurrentPerform(iterations: 64) { candidate in
                modal.dismiss(candidate)
            }
            dismissalsReturned.fulfill()
        }

        await fulfillment(of: [dismissalsReturned, resumed], timeout: 2)
        let storedResult = try XCTUnwrap(modal.result)
        XCTAssertTrue(modal.isDismissed)
        XCTAssertEqual(results.snapshot, Array(repeating: storedResult, count: 64))
    }

    /// DIA-013 — existing dialog methods remain source-compatible.
    func testDIA013ExistingDialogMethodsRemainSourceCompatible() async {
        let sut: any DialogService = NullDialogService.INSTANCE

        let openPath = await sut.pickFileToOpen()
        let savePath = await sut.pickFileToSave()
        let confirmed = await sut.confirm("Proceed?")

        XCTAssertNil(openPath)
        XCTAssertNil(savePath)
        XCTAssertFalse(confirmed)
        await sut.notify("Done")
    }
}

private final class LockedModalResults {
    private let lock = NSLock()
    private var values: [Int] = []

    func append(_ value: Int) {
        lock.withLock { values.append(value) }
    }

    var snapshot: [Int] {
        lock.withLock { values }
    }
}

private final class HostDialogService: DialogService {
    func pickFileToOpen(filter: FileFilter?, title: String?) async -> String? { nil }
    func pickFileToSave(filter: FileFilter?, title: String?, suggestedName: String?) async -> String? { nil }
    func confirm(_ message: String, title: String?) async -> Bool { false }
    func notify(_ message: String, title: String?, severity: NotificationSeverity) async {}

    func present<M: ModalVM>(_ modalVM: M) async -> M.Result {
        modalVM.dismiss("accepted" as! M.Result)
        return await modalVM.waitResult()
    }
}
