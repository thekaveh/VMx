//
// HostLifecycleTests — runs the showcase's SwiftUI bridge in a real AppKit
// window on the macOS main run loop (#360). The VM-level suites run headless;
// this one checks what only a host can: appearance, disappearance, and that a
// model change made on a worker thread reaches the view on the main thread.
//
// Every wait is an XCTestExpectation with a bounded timeout, which runs the
// main run loop, never a fixed delay.
//
import AppKit
import SwiftUI
import VMx
import XCTest
@testable import NotesShowcase

/// Records what the hosted view observed, on whichever thread it ran.
private final class HostProbe {
    let appeared: XCTestExpectation
    let disappeared: XCTestExpectation
    let delivered: XCTestExpectation
    private(set) var deliveriesOffMain = 0
    private(set) var renderedTitles: [String] = []

    init(_ test: XCTestCase) {
        appeared = test.expectation(description: "onAppear")
        disappeared = test.expectation(description: "onDisappear")
        delivered = test.expectation(description: "worker change delivered")
        // One model change publishes "model" and "modeledHint", so the view
        // receives it more than once; SwiftUI may also repeat appearance calls.
        for expectation in [appeared, disappeared, delivered] {
            expectation.assertForOverFulfill = false
        }
    }

    func record(_ title: String) {
        if !Thread.isMainThread {
            deliveriesOffMain += 1
        }
        renderedTitles.append(title)
        if title == "from worker" {
            delivered.fulfill()
        }
    }
}

private struct ProbeView: View {
    @StateObject private var bound: BindableVM<ComponentVMOf<String>>
    private let probe: HostProbe

    init(vm: ComponentVMOf<String>, probe: HostProbe) {
        _bound = StateObject(wrappedValue: BindableVM(vm))
        self.probe = probe
    }

    var body: some View {
        Text(bound.vm.model)
            .onAppear { probe.appeared.fulfill() }
            .onDisappear { probe.disappeared.fulfill() }
            .onReceive(bound.objectWillChange) { _ in probe.record(bound.vm.model) }
    }
}

final class HostLifecycleTests: XCTestCase {
    @MainActor
    func testHostedViewAppearsReceivesWorkerChangesOnTheMainThreadAndDisappears() throws {
        let os = ProcessInfo.processInfo.operatingSystemVersion
        XCTAssertGreaterThanOrEqual(os.majorVersion, 13, "the showcase declares macOS 13 or later")
        print("Host runtime: macOS \(os.majorVersion).\(os.minorVersion).\(os.patchVersion)")

        // A test process has no running app; AppKit windows need the shared one.
        _ = NSApplication.shared
        let vm = try ComponentVMOf<String>.builder()
            .name("title").model("draft").withNullServices().build()
        try vm.construct()
        let probe = HostProbe(self)
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 240, height: 80),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        window.isReleasedWhenClosed = false
        window.contentViewController = NSHostingController(
            rootView: ProbeView(vm: vm, probe: probe)
        )
        window.orderFront(nil)
        wait(for: [probe.appeared], timeout: 10)

        DispatchQueue.global().async {
            vm.model = "from worker"
        }
        wait(for: [probe.delivered], timeout: 10)
        XCTAssertEqual(probe.deliveriesOffMain, 0, "every change reached the view on the main thread")
        XCTAssertEqual(probe.renderedTitles.last, "from worker")

        window.contentViewController = nil
        window.close()
        wait(for: [probe.disappeared], timeout: 10)
        XCTAssertTrue(vm.isConstructed, "closing the window leaves the VM to its owner")
        vm.dispose()
    }
}
