//
// ContainerSupport — the collection-change delivery, late-child source and
// auto-construct-on-add helpers shared by `CompositeVM` and `GroupVM`
// (spec/06 §4, §5.1, spec/07). Each container passes its own state; its
// members only forward here.
//
import Foundation
import Combine

/// Helpers shared by composites and groups. Each container passes the
/// private state a helper reads: its membership gate, its start records, its
/// auto-construct-on-add flag and its collection-change subject.
enum ContainerSupport {
    /// Delivers `event` to local subscribers first, then publishes the
    /// equivalent `CollectionChangedMessage` on the container's `hub`, sent
    /// by the container (spec/01 §1.4, spec/06 §4, spec/07, ADR-0142). Like
    /// the local delivery, it runs outside `gate`; publication uses the hub's
    /// ordinary `send`, so hub transactions defer it. A container whose
    /// disposal is requested or deferred publishes nothing. The check runs
    /// after the local subscribers return, so a subscriber that disposes the
    /// container suppresses the hub message of that change (ADR-0190).
    static func deliverCollectionChanged(
        _ event: CollectionChangedEvent,
        from container: ComponentVMBase,
        subject: PassthroughSubject<CollectionChangedEvent, Never>,
        gate: NSRecursiveLock,
        disposalPending: () -> Bool
    ) {
        subject.send(event)
        guard !gate.withLock(disposalPending) else { return }
        container.hub.send(event.hubMessage(sentBy: container))
    }

    /// Supplies the construct walk with each child added while it runs whose
    /// add starts it, with that add's start record; the walk joins such a
    /// child and never starts it. A late child no add starts is skipped
    /// (spec/02 §6, spec/06 §5.1). The final pull drops every record.
    /// `children` reads the container's current children under `gate`.
    static func lateChildSource<Container: ComponentVMBase, Child: ComponentVMBase>(
        for container: Container,
        after snapshot: [Child],
        scope: LateChildStarts.Scope?,
        autoConstructOnAdd: Bool,
        starts: LateChildStarts,
        gate: NSRecursiveLock,
        children: @escaping (Container) -> [Child]
    ) -> LateChildSource? {
        guard autoConstructOnAdd, let scope else { return nil }
        // Shared by the late pull and the commit-time seal.
        var visited = Set(snapshot.map(ObjectIdentifier.init))
        // Under `gate`: the next unvisited child with a start record in this
        // walk's scope; a child without one is skipped.
        let pullLocked: () -> (child: ComponentVMBase, record: LateChildStarts.Record)? = {
            [unowned container] in
            while true {
                guard let late = children(container).first(where: {
                    !visited.contains(ObjectIdentifier($0))
                }) else { return nil }
                visited.insert(ObjectIdentifier(late))
                if let record = starts.take(late, from: scope) { return (late, record) }
            }
        }
        return LateChildSource(
            starts: starts,
            scope: scope,
            next: { [weak container] in
                guard let container else { return nil }
                let late = gate.withLock { pullLocked() }
                if late == nil { starts.probe(container, .lastScanDone) }
                return late
            },
            seal: { [weak container] in
                guard let container else { return .abandoned }
                // Commit or keep walking (spec/06 §5.1): with no late child
                // left, the commit step writes `.constructed` in this same
                // gate section, so a later add reads `.constructed`, and ends
                // the walk's scope. An abandoned walk writes nothing.
                let outcome: LateChildSeal = gate.withLock {
                    if let late = pullLocked() { return .late(late.child, late.record) }
                    let committed = container._flipConstructedForSeal()
                    starts.endWalk(scope)
                    return committed ? .sealed : .abandoned
                }
                if case .sealed = outcome { starts.probe(container, .sealed) }
                return outcome
            },
            willSeal: { [weak container] in
                guard let container else { return }
                starts.probe(container, .sealing)
            }
        )
    }

    /// Call under the container's membership gate, in the section that
    /// attaches `child`. Registers a start record when this add will start
    /// the child: with auto-construct-on-add while the container is
    /// `Constructing`.
    static func registerLateStartLocked(
        _ child: ComponentVMBase,
        in container: ComponentVMBase,
        autoConstructOnAdd: Bool,
        starts: LateChildStarts
    ) -> LateChildStarts.Record? {
        starts.attachLocked(
            child, starting: autoConstructOnAdd && container.status == .constructing
        )
    }

    /// Auto-construct-on-add of a child an add attached; returns the child's
    /// construct error. With a start `record` (the container was
    /// `Constructing` at the attach), a `Destructed` child starts now. A
    /// construct that another thread started after the status read is left
    /// alone: the walk joins it, and the add neither starts nor waits for it
    /// (ADR-0218 rule 6). Without a record, the child starts only when the
    /// container is `Constructed`: one attached before the walk's snapshot is
    /// constructed by the walk (spec/06 §5.1). This helper never marks the
    /// record done: the add calls `finishLateStart` after it ends its
    /// membership transaction, on success and after its undo, so a walk that
    /// waits on the record resumes only then (ADR-0186, ADR-0218 rule 4).
    static func autoConstructAttached(
        _ child: ComponentVMBase,
        in container: ComponentVMBase,
        record: LateChildStarts.Record?,
        autoConstructOnAdd: Bool,
        starts: LateChildStarts
    ) -> Error? {
        guard autoConstructOnAdd else { return nil }
        guard record != nil else {
            guard container.isConstructed else { return nil }
            do { try child.construct() } catch { return error }
            return nil
        }
        starts.probe(child, .attached)
        if child.status == .destructed {
            starts.probe(child, .starting)
            do {
                try child.construct()
            } catch let error as StatusTransitionError {
                guard child._isInTransition(.constructing) || child.status == .constructed else {
                    return error
                }
            } catch {
                return error
            }
        }
        return nil
    }

    /// Marks an add's start attempt done. The add calls it after it ended
    /// its membership transaction (ADR-0218 rule 4).
    static func finishLateStart(
        _ child: ComponentVMBase,
        _ record: LateChildStarts.Record?,
        in container: ComponentVMBase,
        starts: LateChildStarts
    ) {
        guard let record else { return }
        starts.finish(child, record, constructing: container.status == .constructing)
    }

    /// The lifecycle compensation of a child that a failed add, insert,
    /// index replacement or population attached (spec/06 §4.2). Only a child
    /// that was `Destructed` before the change is compensated. A child whose
    /// construct is still in flight is not waited for: once that construct
    /// settles at `Constructed` and the child has no parent, VMx calls its
    /// `destruct()`, and the failed change reports no failure of that call
    /// (ADR-0218 rule 7). A `Constructed` child is destructed now. Returns
    /// that destruct's error.
    static func compensateAutoConstruct(
        _ child: ComponentVMBase,
        originalStatus: ConstructionStatus
    ) -> Error? {
        guard originalStatus == .destructed else { return nil }
        let deferred = child._awaitSettle(from: .constructing) { [weak child] in
            guard let child, child.status == .constructed,
                  child._transferOwnershipParent == nil else { return }
            // A background child reports a destruct hook failure through its
            // own background path; nobody waits for this call.
            try? child.destruct()
        }
        guard deferred == nil, child.status == .constructed else { return nil }
        do { try child.destruct() } catch { return error }
        return nil
    }
}

/// The inner error of `ContainerOwnershipError.attachmentFailed` when a
/// membership change finds the container's membership transaction in
/// progress, on this thread (ADR-0118) or on another thread (ADR-0187).
struct ContainerMembershipTransactionError: Error {}
