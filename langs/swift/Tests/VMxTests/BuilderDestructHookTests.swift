//
// Builder, options and initializer destruct hooks (#1599).
//
// Every Swift construction path accepts a throwing `onDestruct`, as the
// `onConstruct` hook already does. A builder-built view-model rolls back to
// `.constructed` when that hook throws (spec 02 §2.5; the destruct half of
// `LifecycleTests.testLife014ThrowingHookRollsBackStatus`).
//
import XCTest
@testable import VMx

final class BuilderDestructHookTests: XCTestCase {

    private struct HookError: Error {}

    /// Not `Equatable`, so `ComponentVMOf<Box>` selects the designated initializer.
    private struct Box { var value: Int }

    /// Compiles only when every construction path takes a throwing destruct hook.
    func testEveryConstructionPathAcceptsThrowingDestructHook() throws {
        // Builders (six).
        _ = try ComponentVM.builder().name("component")
            .withNullServices()
            .onDestruct { throw HookError() }
            .build()
        _ = try ComponentVMOf<Box>.builder().name("component-of")
            .model(Box(value: 1))
            .withNullServices()
            .onDestruct { throw HookError() }
            .build()
        _ = try ReadonlyComponentVMOfBuilder<Box>().name("readonly-of")
            .model(Box(value: 1))
            .withNullServices()
            .onDestruct { throw HookError() }
            .build()
        _ = try CompositeVM<ComponentVM>.builder().name("composite")
            .withNullServices()
            .children { [] }
            .onDestruct { throw HookError() }
            .build()
        _ = try CompositeVMOf<Int, ComponentVM>.builder().name("composite-of")
            .withNullServices()
            .childrenModels { [] }
            .childModelToChildViewModel { _ in
                ComponentVM(name: "child", hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE)
            }
            .onDestruct { throw HookError() }
            .build()
        _ = try GroupVM<ComponentVM>.builder().name("group")
            .withNullServices()
            .children { [] }
            .onDestruct { throw HookError() }
            .build()

        // Options structs, through their factories (four).
        _ = try ComponentVM.create(ComponentVMOptions(
            name: "options-component", hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE,
            onDestruct: { throw HookError() }
        ))
        _ = try ComponentVMOf<Box>.create(ComponentVMOfOptions<Box>(
            name: "options-component-of", model: Box(value: 1),
            hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE,
            onDestruct: { throw HookError() }
        ))
        _ = try CompositeVM<ComponentVM>.create(CompositeVMOptions<ComponentVM>(
            name: "options-composite", hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE,
            children: { [] },
            onDestruct: { throw HookError() }
        ))
        _ = try GroupVM<ComponentVM>.create(GroupVMOptions<ComponentVM>(
            name: "options-group", hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE,
            children: { [] },
            onDestruct: { throw HookError() }
        ))

        // Designated and constrained initializers (five).
        _ = ComponentVMOf<Box>(
            name: "init-component-of", initialModel: Box(value: 1),
            hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE,
            onDestruct: { throw HookError() }
        )
        // `Equatable` model, no `modelEquals:`: selects the `where Model: Equatable` initializer.
        _ = ComponentVMOf<Int>(
            name: "init-component-of-equatable", initialModel: 1,
            hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE,
            onDestruct: { throw HookError() }
        )
        _ = CompositeVM<ComponentVM>(
            name: "init-composite",
            hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE,
            onDestruct: { throw HookError() }
        )
        _ = CompositeVMOf<Int, ComponentVM>(
            name: "init-composite-of",
            hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE,
            childrenModels: { [] },
            childModelToChildViewModel: { _ in
                ComponentVM(name: "child", hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE)
            },
            onDestruct: { throw HookError() }
        )
        _ = GroupVM<ComponentVM>(
            name: "init-group",
            hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE,
            onDestruct: { throw HookError() }
        )
    }

    /// The destruct half of LIFE-014 for a builder-built `ComponentVMOf`.
    func testBuilderBuiltComponentVMOfRollsBackWhenDestructHookThrows() throws {
        var failDestruct = true
        let vm = try ComponentVMOf<Int>.builder().name("builder-of")
            .model(1)
            .services(hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE)
            .onDestruct { if failDestruct { throw HookError() } }
            .build()
        try vm.construct()

        XCTAssertThrowsError(try vm.destruct()) { XCTAssertTrue($0 is HookError) }
        XCTAssertEqual(vm.status, .constructed, "failed destruct must roll back to Constructed")

        failDestruct = false
        try vm.destruct()
        XCTAssertEqual(vm.status, .destructed,
            "a retry with a non-throwing destruct hook reaches Destructed")
    }

    /// The destruct half of LIFE-014 for a builder-built `CompositeVM`.
    func testBuilderBuiltCompositeVMRollsBackWhenDestructHookThrows() throws {
        var failDestruct = true
        let vm = try CompositeVM<ComponentVM>.builder().name("builder-composite")
            .services(hub: MessageHub(), dispatcher: ImmediateDispatcher.INSTANCE)
            .children { [] }
            .onDestruct { if failDestruct { throw HookError() } }
            .build()
        try vm.construct()

        XCTAssertThrowsError(try vm.destruct()) { XCTAssertTrue($0 is HookError) }
        XCTAssertEqual(vm.status, .constructed, "failed destruct must roll back to Constructed")

        failDestruct = false
        try vm.destruct()
        XCTAssertEqual(vm.status, .destructed,
            "a retry with a non-throwing destruct hook reaches Destructed")
    }
}
