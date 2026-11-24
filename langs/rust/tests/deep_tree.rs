//! Deep-chain tests for `walk`, `walk_expanded`, `find`, `depth`, `path`, a
//! move of a subtree and `invalidate_subtree` (issue #1912). The tree is
//! 10,000 levels deep. Each test body runs on a thread with a 512 KiB stack,
//! so an implementation that recurses once per level overflows that stack and
//! aborts the test binary.

use std::thread;
use vmx::{find, walk, walk_expanded, HierarchicalVm, MessageHub};

const LEVELS: usize = 10_000;
const STACK_BYTES: usize = 512 * 1024;

/// A chain of `levels` nodes whose model is the node's depth. Children come
/// from factories, so building the chain does not touch any cache. The node
/// at depth `depth` materializes one child until the last level. Each child
/// gets its own hub: on one shared hub, every structural message reaches every
/// node, so a chain's messages cost O(levels²).
fn chain(depth: usize, levels: usize, hub: MessageHub) -> HierarchicalVm<usize> {
    HierarchicalVm::with_children_factory(
        format!("n{depth}"),
        depth,
        move |_| {
            if depth + 1 == levels {
                Vec::new()
            } else {
                vec![chain(depth + 1, levels, MessageHub::new())]
            }
        },
        false,
        hub,
    )
}

/// Materializes the chain top-down and returns its nodes, root first.
fn materialize(root: &HierarchicalVm<usize>) -> Vec<HierarchicalVm<usize>> {
    let mut nodes = vec![root.clone()];
    loop {
        let next = nodes[nodes.len() - 1].children().into_iter().next();
        match next {
            Some(child) => nodes.push(child),
            None => return nodes,
        }
    }
}

/// Detaches the chain bottom-up, so that dropping it does not recurse once per
/// level. Dropping a chain root in one step overflows a thread stack.
fn release(root: &HierarchicalVm<usize>) {
    let nodes = materialize(root);
    for pair in nodes.windows(2).rev() {
        pair[0]
            .remove_child(&pair[1])
            .expect("the child is detached from its parent");
    }
}

/// Runs `body` on a thread with a 512 KiB stack and waits for it to finish. A
/// panic in `body` is raised again on the calling thread.
fn on_small_stack(body: impl FnOnce() + Send + 'static) {
    let handle = thread::Builder::new()
        .stack_size(STACK_BYTES)
        .spawn(body)
        .expect("the test thread starts");
    if let Err(panic) = handle.join() {
        std::panic::resume_unwind(panic);
    }
}

#[test]
fn deep_chain_walks_find_and_depth_reach_the_last_level() {
    on_small_stack(|| {
        let root = chain(0, LEVELS, MessageHub::new());

        let nodes = walk(&root).expect("the chain walks");
        let target = nodes[LEVELS - 1].clone();
        let last = target
            .downcast::<HierarchicalVm<usize>>()
            .expect("the last node is a HierarchicalVm");

        assert_eq!(nodes.len(), LEVELS);
        for (index, node) in nodes.iter().enumerate() {
            let node = node
                .downcast::<HierarchicalVm<usize>>()
                .expect("every node is a HierarchicalVm");
            assert_eq!(node.model(), index, "walk yields the chain in pre-order");
        }
        assert_eq!(last.depth(), LEVELS - 1);
        assert_eq!(last.path().len(), LEVELS);
        assert_eq!(walk_expanded(&root).expect("the chain walks").len(), LEVELS);
        let found = find(&root, |node| *node == target).expect("the chain is searched");
        assert!(found.is_some_and(|hit| hit == target));

        release(&root);
    });
}

#[test]
fn deep_chain_moves_under_a_new_parent() {
    on_small_stack(|| {
        let hub = MessageHub::new();
        let root = chain(0, LEVELS, hub.clone());
        // Materialize top-down in a loop, so the move itself is what recurses.
        let nodes = materialize(&root);
        let last = nodes[LEVELS - 1].clone();
        assert_eq!(last.depth(), LEVELS - 1);
        let new_root =
            HierarchicalVm::with_children_factory("new-root", 0usize, |_| Vec::new(), false, hub);

        new_root
            .add_child(root.clone())
            .expect("the deep subtree moves under the new parent");

        assert!(root.parent().is_some_and(|parent| parent == new_root));
        assert_eq!(last.depth(), LEVELS);
        let path = last.path();
        assert_eq!(path.len(), LEVELS + 1);
        assert!(path[0] == new_root);
        assert!(path[1] == root);
        // The deepest node now shares its tree root with new_root, so new_root
        // is one of its ancestors and must not become its child.
        assert!(
            last.add_child(new_root.clone()).is_err(),
            "the moved subtree restamps its nodes with the new tree root"
        );

        release(&new_root);
    });
}

#[test]
fn deep_chain_invalidate_subtree_clears_every_level() {
    on_small_stack(|| {
        let root = chain(0, LEVELS, MessageHub::new());
        let nodes = materialize(&root);
        assert!(nodes.iter().all(|node| node.is_children_materialized()));

        root.invalidate_subtree();

        assert!(nodes.iter().all(|node| !node.is_children_materialized()));
        assert!(root.is_root());
        // The factory runs again on the next read, so the chain rebuilds.
        assert_eq!(materialize(&root).len(), LEVELS);

        release(&root);
    });
}
