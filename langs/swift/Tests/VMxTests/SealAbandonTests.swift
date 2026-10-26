import Combine
import Foundation
import XCTest
@testable import VMx

/// A disposal that cancels a construct walk while its commit-time seal runs
/// publishes no `.destructed` rollback ahead of the disposal (spec/06 §5.1,
/// #744). The walk had finished, so the container commits `.constructed` as
/// it would have without the seal, then the disposal publishes `.disposed`.
/// Every wait is bounded.
final class SealAbandonTests: XCTestCase {
    private final class Locked<T> {
        private let lock = NSLock()
        private var stored: T
        init(_ value: T) { stored = value }
        var value: T {
            get { lock.withLock { stored } }
            set { lock.withLock { stored = newValue } }
        }
        func mutate(_ change: (inout T) -> Void) { lock.withLock { change(&stored) } }
    }

    private func rootStatusesWhenDisposalCancelsTheSeal(_ kind: String) throws -> [ConstructionStatus] {
        let hub = MessageHub()
        let dispatcher = ManualDispatcher()
        let first = try ComponentVM.builder()
            .name("first").services(hub: hub, dispatcher: dispatcher).background(true).build()
        let root: ComponentVMBase
        let setProbe: (@escaping (ComponentVMBase, LateChildStage) -> Void) -> Void
        if kind == "composite" {
            let composite = CompositeVM<ComponentVM>(
                name: "root", hub: hub, dispatcher: dispatcher, autoConstructOnAdd: true
            )
            _ = composite.addResult(first)
            setProbe = { composite.lateChildProbeForTesting = $0 }
            root = composite
        } else {
            let group = GroupVM<ComponentVM>(
                name: "root", hub: hub, dispatcher: dispatcher, autoConstructOnAdd: true
            )
            _ = group.addResult(first)
            setProbe = { group.lateChildProbeForTesting = $0 }
            root = group
        }

        let log = Locked<[ConstructionStatus]>([])
        let childDisposing = DispatchSemaphore(value: 0)
        let goDispose = DispatchSemaphore(value: 0)
        let subscription = hub.messages
            .compactMap { $0 as? ConstructionStatusChangedMessage }
            .sink { message in
                if message.senderName == "root" { log.mutate { $0.append(message.status) } }
                if message.senderName == "first" && message.status == .disposed {
                    // Hold the disposal's child cascade until the seal resumed.
                    childDisposing.signal()
                    _ = goDispose.wait(timeout: .now() + 5)
                }
            }
        defer { subscription.cancel() }

        try root.construct()
        XCTAssertEqual(root.status, .constructing, kind)

        let sealing = DispatchSemaphore(value: 0)
        let goSeal = DispatchSemaphore(value: 0)
        let paused = Locked(false)
        setProbe { _, stage in
            guard stage == .sealing, !paused.value else { return }
            paused.value = true
            sealing.signal()
            _ = goSeal.wait(timeout: .now() + 5)
        }

        // The first child settles on a pump thread; the walk ends there and
        // its commit-time seal pauses before it checks for cancellation.
        let pumped = DispatchSemaphore(value: 0)
        Thread {
            for _ in 0..<5 {
                dispatcher.flushBackground()
                dispatcher.flushForeground()
            }
            pumped.signal()
        }.start()
        XCTAssertEqual(sealing.wait(timeout: .now() + 5), .success, "\(kind): the seal starts")

        // A disposal from another thread cancels the walk, then holds in its
        // child cascade before the container's own disposal.
        let disposed = DispatchSemaphore(value: 0)
        Thread {
            root.dispose()
            disposed.signal()
        }.start()
        XCTAssertEqual(
            childDisposing.wait(timeout: .now() + 5), .success, "\(kind): the cascade starts"
        )
        // The seal resumes and finds its walk cancelled. Its terminal status
        // is committed before its publication, which queues behind the held
        // delivery; release the cascade once that status is decided.
        goSeal.signal()
        let deadline = Date().addingTimeInterval(5)
        while root.status == .constructing && Date() < deadline { usleep(1_000) }
        XCTAssertNotEqual(root.status, .constructing, "\(kind): the seal commits a status")
        goDispose.signal()
        XCTAssertEqual(pumped.wait(timeout: .now() + 5), .success, "\(kind): the seal finishes")
        XCTAssertEqual(disposed.wait(timeout: .now() + 5), .success, "\(kind): the disposal ends")
        XCTAssertEqual(root.status, .disposed, kind)
        return log.value
    }

    func testDisposalDuringTheSealPublishesNoRollback() throws {
        for kind in ["composite", "group"] {
            XCTAssertEqual(
                try rootStatusesWhenDisposalCancelsTheSeal(kind),
                [.constructing, .constructed, .disposed],
                kind
            )
        }
    }

    /// A sealed commit stops counting as pending when its publication starts,
    /// so a subscriber of `.constructed` sees the same predicates as without
    /// the seal.
    func testSubscribersOfConstructedSeeTheCommitCompleted() throws {
        for kind in ["composite", "group"] {
            let hub = MessageHub()
            let dispatcher = ManualDispatcher()
            let first = try ComponentVM.builder()
                .name("first").services(hub: hub, dispatcher: dispatcher).background(true).build()
            let root: ComponentVMBase
            if kind == "composite" {
                let composite = CompositeVM<ComponentVM>(
                    name: "root", hub: hub, dispatcher: dispatcher, autoConstructOnAdd: true
                )
                _ = composite.addResult(first)
                root = composite
            } else {
                let group = GroupVM<ComponentVM>(
                    name: "root", hub: hub, dispatcher: dispatcher, autoConstructOnAdd: true
                )
                _ = group.addResult(first)
                root = group
            }
            let seen = Locked<[Bool]>([])
            let subscription = hub.messages
                .compactMap { $0 as? ConstructionStatusChangedMessage }
                .filter { $0.senderName == "root" && $0.status == .constructed }
                .sink { _ in seen.mutate { $0.append(root.canReconstruct()) } }
            defer { subscription.cancel() }
            try root.construct()
            for _ in 0..<5 {
                dispatcher.flushBackground()
                dispatcher.flushForeground()
            }
            XCTAssertEqual(root.status, .constructed, kind)
            XCTAssertEqual(seen.value, [true], kind)
        }
    }
}
