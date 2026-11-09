//
// CatchableRefusalTests.swift — ADR-0217, #1349.
//
// `FilteredCompositeVM.setCurrentResult(_:)`, `removeAtResult(_:)` on
// `CompositeVM`, `GroupVM` and `ForwardingCompositeVM`, and
// `DerivedProperty.fromSourcesResult` report invalid input as a failure
// instead of trapping. The other flavors raise a catchable error for the
// same input.
//
import Combine
import XCTest
@testable import VMx

final class CatchableRefusalTests: XCTestCase {
    private func child(_ name: String) throws -> ComponentVM {
        try ComponentVM.builder().name(name).withNullServices().build()
    }

    private func composite(_ names: String...) throws -> CompositeVM<ComponentVM> {
        let vm = try CompositeVM<ComponentVM>.builder()
            .name("composite").withNullServices().children { [] }.build()
        for name in names { vm.add(try child(name)) }
        return vm
    }

    private func group(_ names: String...) throws -> GroupVM<ComponentVM> {
        let vm = try GroupVM<ComponentVM>.builder()
            .name("group").withNullServices().children { [] }.build()
        for name in names { vm.add(try child(name)) }
        return vm
    }

    private func indexError(
        _ result: Result<Void, ContainerOwnershipError>,
        file: StaticString = #filePath,
        line: UInt = #line
    ) -> VMCollectionIndexError? {
        guard case let .failure(.attachmentFailed(error)) = result else {
            XCTFail("expected an index failure, got \(result)", file: file, line: line)
            return nil
        }
        return error as? VMCollectionIndexError
    }

    func testFilteredSetCurrentResultRefusesAHiddenItem() throws {
        let src = try composite("alpha", "bee", "gamma")
        let sut = FilteredCompositeVM(src) { $0.name.contains("a") }
        XCTAssertEqual(sut.current?.name, "alpha")
        var changes = 0
        let subscription = sut.changed.sink { changes += 1 }

        let result = sut.setCurrentResult(src.at(1))

        guard case let .failure(error) = result else { return XCTFail("a hidden item must fail") }
        XCTAssertEqual(error.reason, .notVisible)
        XCTAssertEqual(error.memberName, "bee")
        XCTAssertEqual(sut.current?.name, "alpha")
        XCTAssertEqual(changes, 0)

        // A visible item and nil still commit.
        XCTAssertNoThrow(try sut.setCurrentResult(sut.visible[1]).get())
        XCTAssertEqual(sut.current?.name, "gamma")
        XCTAssertNoThrow(try sut.setCurrentResult(nil).get())
        XCTAssertNil(sut.current)
        XCTAssertEqual(changes, 2)
        subscription.cancel()
    }

    func testCompositeRemoveAtResultRefusesAnOutOfRangeIndex() throws {
        let sut = try composite("a", "b")
        var events: [CollectionChangedEvent] = []
        let subscription = sut.collectionChanged.sink { events.append($0) }

        for index in [-1, sut.count] {
            let error = indexError(sut.removeAtResult(index))
            XCTAssertEqual(error, VMCollectionIndexError(index: index, count: 2))
            // The non-throwing form changes nothing either.
            sut.removeAt(index)
        }

        XCTAssertEqual(sut.snapshot().map(\.name), ["a", "b"])
        XCTAssertTrue(events.isEmpty)
        XCTAssertNoThrow(try sut.removeAtResult(0).get())
        XCTAssertEqual(sut.snapshot().map(\.name), ["b"])
        subscription.cancel()
    }

    func testGroupRemoveAtResultRefusesAnOutOfRangeIndex() throws {
        let sut = try group("a", "b")
        var events: [CollectionChangedEvent] = []
        let subscription = sut.collectionChanged.sink { events.append($0) }

        for index in [-1, sut.count] {
            let error = indexError(sut.removeAtResult(index))
            XCTAssertEqual(error, VMCollectionIndexError(index: index, count: 2))
            sut.removeAt(index)
        }

        XCTAssertEqual(sut.snapshot().map(\.name), ["a", "b"])
        XCTAssertTrue(events.isEmpty)
        XCTAssertNoThrow(try sut.removeAtResult(1).get())
        XCTAssertEqual(sut.snapshot().map(\.name), ["a"])
        subscription.cancel()
    }

    func testForwardingRemoveAtResultReportsTheWrappedError() throws {
        let wrapped = try composite("a", "b")
        let sut = ForwardingCompositeVM<ComponentVM>(wrapped)

        let error = indexError(sut.removeAtResult(sut.count))

        XCTAssertEqual(error, VMCollectionIndexError(index: 2, count: 2))
        XCTAssertEqual(wrapped.snapshot().map(\.name), ["a", "b"])
    }

    func testFromSourcesResultRefusesAnEmptySourceList() throws {
        let empty = DerivedProperty<Int>.fromSourcesResult([]) { _ in 0 }
        guard case .failure(.noSources) = empty else { return XCTFail("an empty list must fail") }

        let subject = CurrentValueSubject<Int, Never>(7)
        let result = DerivedProperty<Int>.fromSourcesResult(
            [subject.map { $0 as Any }.eraseToAnyPublisher()]
        ) { values in values[0] as! Int }
        let property = try result.get()
        XCTAssertEqual(try property.value, 7)
        property.dispose()
    }
}
