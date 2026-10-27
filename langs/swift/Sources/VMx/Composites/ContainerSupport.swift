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
    /// ordinary `send`, so hub transactions defer it. A disposed container
    /// publishes nothing.
    static func deliverCollectionChanged(
        _ event: CollectionChangedEvent,
        from container: ComponentVMBase,
        subject: PassthroughSubject<CollectionChangedEvent, Never>,
        gate: NSRecursiveLock,
        disposeRequested: () -> Bool
    ) {
        subject.send(event)
        guard !gate.withLock(disposeRequested) else { return }
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
                guard let container else { return nil }
                // Commit or keep walking (spec/06 §5.1): with no late child
                // left, flip the state in this same gate section, so a later
                // add reads `.constructed`, and end the walk's scope.
                return gate.withLock {
                    if let late = pullLocked() { return late }
                    container._flipConstructedForSeal()
                    starts.endWalk(scope)
                    return nil
                }
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
    /// `Constructing` at the attach), a `Destructed` child starts now and the
    /// record is marked done right after the attempt, before the add
    /// publishes anything. Without one, the child starts only when the
    /// container is `Constructed`: one attached before the walk's snapshot is
    /// constructed by the walk (spec/06 §5.1).
    static func autoConstructAttached(
        _ child: ComponentVMBase,
        in container: ComponentVMBase,
        record: LateChildStarts.Record?,
        autoConstructOnAdd: Bool,
        starts: LateChildStarts
    ) -> Error? {
        guard autoConstructOnAdd else { return nil }
        guard let record else {
            guard container.isConstructed else { return nil }
            do { try child.construct() } catch { return error }
            return nil
        }
        starts.probe(child, .attached)
        defer {
            starts.finish(child, record, constructing: container.status == .constructing)
        }
        guard child.status == .destructed else { return nil }
        do { try child.construct() } catch { return error }
        return nil
    }
}
