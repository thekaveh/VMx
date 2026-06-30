//
// Command truth-table fixture conformance test.
//
// Claimed IDs: CMD-007 (command truth-table matches fixture).
//
import XCTest
import Combine
@testable import VMx

// Decodable model for command-truthtable.json
private struct TruthTableFixture: Decodable {
    struct Case: Decodable {
        let id: String
        let predicate: Bool?
        let task: String?
        let trigger_emits: Bool
        let can_execute: Bool
        let execute_invokes_task: Bool
        let can_execute_changed_fires: Bool
    }
    let cases: [Case]
}

final class RelayCommandTruthTableTests: XCTestCase {

    /// CMD-007 — Command truth-table matches fixture.
    func testCmd007TruthTableMatchesFixture() throws {
        let url = try XCTUnwrap(
            Bundle.module.url(forResource: "command-truthtable", withExtension: "json"),
            "command-truthtable.json not found in Bundle.module"
        )
        let data = try Data(contentsOf: url)
        let fixture = try JSONDecoder().decode(TruthTableFixture.self, from: data)

        for row in fixture.cases {
            var taskInvoked = 0
            var canExecuteChangedFired = 0
            let trigger = PassthroughSubject<Void, Never>()

            var builder = RelayCommand.builder()
            if let pred = row.predicate {
                builder = builder.predicate { pred }
            }
            if row.task != nil {
                builder = builder.task { taskInvoked += 1 }
            }
            builder = builder.triggers(trigger.eraseToAnyPublisher())

            let cmd = builder.build()
            let cancellable = cmd.canExecuteChanged.sink { _ in canExecuteChangedFired += 1 }

            if row.trigger_emits { trigger.send(()) }
            let canExec = cmd.canExecute()
            cmd.execute()

            XCTAssertEqual(canExec, row.can_execute,
                           "\(row.id): can_execute expected \(row.can_execute)")
            XCTAssertEqual(taskInvoked > 0, row.execute_invokes_task,
                           "\(row.id): execute_invokes_task expected \(row.execute_invokes_task)")
            XCTAssertEqual(canExecuteChangedFired > 0, row.can_execute_changed_fires,
                           "\(row.id): can_execute_changed_fires expected \(row.can_execute_changed_fires)")

            cancellable.cancel()
        }
    }
}
