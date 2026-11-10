//
// TSanProofTests.swift — throwaway proof for #1407 criterion 2. Do not merge.
//
// Two threads write one variable without a lock. The `thread sanitizer` job
// must report a data race and fail.
//

import Foundation
import XCTest

private final class UnguardedBox: @unchecked Sendable {
    var value = 0
}

final class TSanProofTests: XCTestCase {
    func testUnguardedWritesFromTwoThreads() {
        let box = UnguardedBox()
        let done = DispatchGroup()
        for _ in 0..<2 {
            done.enter()
            Thread.detachNewThread {
                for i in 0..<10_000 { box.value = i }
                done.leave()
            }
        }
        done.wait()
        XCTAssertGreaterThanOrEqual(box.value, 0)
    }
}
