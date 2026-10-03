//
// FormVMApprovalPublicationTests.swift — approval publication outside the
// form's state lock (#533).
//
// The C# and Python flavors deliver an approval without holding the form's
// state lock. Swift held its lock across `onApproved`, so an approved observer
// that sent on a `MessageHub` while another thread drained that hub, with a
// subscriber reading the form, deadlocked: each thread waited for the other.
// No conformance ID: this is a flavor-local repair.
//

import Combine
import Foundation
import XCTest
@testable import VMx

private struct Ping: Message {
    let senderObject: AnyObject
    let senderName: String
}

final class FormVMApprovalPublicationTests: XCTestCase {

    func testApprovedObserverMaySendWhileAnotherThreadDrainsAHubThatReadsTheForm() {
        let hub = MessageHub()
        let form = FormVM(initial: "saved", persister: { (_: String) in })
        form.setModel("edited")

        let drainerEntered = DispatchSemaphore(value: 0)
        let publisherEntered = DispatchSemaphore(value: 0)
        let drainerFinished = DispatchSemaphore(value: 0)
        let approvalFinished = DispatchSemaphore(value: 0)
        let readLock = NSLock()
        var dirtyReadByDrainer: Bool?

        // The draining thread's subscriber reads the form once the approving
        // thread is inside `onApproved`.
        let hubSubscription = hub.messages.sink { message in
            guard message.senderName == "drainer" else { return }
            drainerEntered.signal()
            _ = publisherEntered.wait(timeout: .now() + 10)
            let dirty = form.isDirty
            readLock.lock()
            dirtyReadByDrainer = dirty
            readLock.unlock()
        }
        // The approving thread's observer sends on the same hub, so it waits
        // until the draining thread has delivered everything.
        let approvedSubscription = form.onApproved.sink { _ in
            publisherEntered.signal()
            hub.send(Ping(senderObject: NSObject(), senderName: "publisher"))
        }
        defer {
            hubSubscription.cancel()
            approvedSubscription.cancel()
        }

        let boxedHub = UncheckedSendableBox(hub)
        DispatchQueue.global().async {
            boxedHub.value.send(Ping(senderObject: NSObject(), senderName: "drainer"))
            drainerFinished.signal()
        }
        XCTAssertEqual(drainerEntered.wait(timeout: .now() + 10), .success)

        let boxedForm = UncheckedSendableBox(form)
        Task.detached {
            try? await boxedForm.value.approveAsync()
            approvalFinished.signal()
        }

        // With the lock held across `onApproved`, both threads would wait on
        // each other forever, so every wait is bounded.
        XCTAssertEqual(
            drainerFinished.wait(timeout: .now() + 10), .success,
            "the draining thread must read the form while the approval is published"
        )
        XCTAssertEqual(approvalFinished.wait(timeout: .now() + 10), .success)
        readLock.lock()
        let dirty = dirtyReadByDrainer
        readLock.unlock()
        XCTAssertEqual(dirty, false, "the reader sees the committed, pristine approval")
    }

    func testAnotherThreadsSetModelWaitsUntilTheApprovalIsPublished() {
        let form = FormVM(initial: "saved", persister: { (_: String) in })
        form.setModel("edited")

        let publisherEntered = DispatchSemaphore(value: 0)
        let releasePublisher = DispatchSemaphore(value: 0)
        let approvalFinished = DispatchSemaphore(value: 0)
        let mutationFinished = DispatchSemaphore(value: 0)
        let orderLock = NSLock()
        var order: [String] = []
        func record(_ event: String) {
            orderLock.lock()
            order.append(event)
            orderLock.unlock()
        }

        let approvedSubscription = form.onApproved.sink { _ in
            publisherEntered.signal()
            _ = releasePublisher.wait(timeout: .now() + 10)
            record("approved delivered")
        }
        defer { approvedSubscription.cancel() }

        let boxedForm = UncheckedSendableBox(form)
        Task.detached {
            try? await boxedForm.value.approveAsync()
            approvalFinished.signal()
        }
        XCTAssertEqual(publisherEntered.wait(timeout: .now() + 10), .success)

        DispatchQueue.global().async {
            boxedForm.value.setModel("after")
            record("setModel returned")
            mutationFinished.signal()
        }
        // Another thread may read the form during publication, but its
        // mutation waits until publication ends (C# and Python parity).
        let readFinished = DispatchSemaphore(value: 0)
        let readLock = NSLock()
        var modelReadDuringPublication: String?
        DispatchQueue.global().async {
            let model = boxedForm.value.model
            readLock.lock()
            modelReadDuringPublication = model
            readLock.unlock()
            readFinished.signal()
        }
        XCTAssertEqual(
            readFinished.wait(timeout: .now() + 10), .success,
            "a reader on another thread does not wait for the publication"
        )
        readLock.lock()
        XCTAssertEqual(modelReadDuringPublication, "edited")
        readLock.unlock()
        XCTAssertEqual(mutationFinished.wait(timeout: .now() + 0.2), .timedOut)
        releasePublisher.signal()

        XCTAssertEqual(approvalFinished.wait(timeout: .now() + 10), .success)
        XCTAssertEqual(mutationFinished.wait(timeout: .now() + 10), .success)
        orderLock.lock()
        let observed = order
        orderLock.unlock()
        XCTAssertEqual(observed, ["approved delivered", "setModel returned"])
        XCTAssertEqual(form.model, "after")
    }
}
