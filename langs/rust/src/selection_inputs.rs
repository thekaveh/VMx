//! The selection-input scope of the Select and Deselect notification
//! (ADR-0242).
//!
//! A container membership transaction, and a container membership section (the
//! membership gate), open the scope. While it is open, a child whose selection
//! inputs changed (its `IsCurrent` flag or its `Parent` link) is queued, not
//! notified. The outermost scope on the thread runs the queue after the gate is
//! released and the transaction has ended, so no `CanExecuteChanged` subscriber
//! runs under a membership gate (spec/06 §4.3). The scope is per thread, and
//! each queued notification runs on the thread that made the change.

use std::cell::RefCell;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::{Mutex, MutexGuard};
use std::thread;

use crate::runtime::lock;

/// One queued notification, run when the outermost scope closes.
type Emit = Box<dyn FnOnce()>;

#[derive(Default)]
struct ScopeState {
    depth: usize,
    pending: Vec<Emit>,
}

thread_local! {
    static SCOPE: RefCell<ScopeState> = RefCell::new(ScopeState::default());
}

/// Opens a scope on the calling thread. Pair each call with [`leave`].
pub(crate) fn enter() {
    SCOPE.with(|scope| scope.borrow_mut().depth += 1);
}

/// Closes a scope. The outermost close runs the queued notifications. The
/// queue is taken out before any notification runs, so a notification may
/// open a scope of its own.
pub(crate) fn leave() {
    let queued = SCOPE.with(|scope| {
        let mut scope = scope.borrow_mut();
        scope.depth = scope.depth.saturating_sub(1);
        if scope.depth == 0 {
            std::mem::take(&mut scope.pending)
        } else {
            Vec::new()
        }
    });
    for emit in queued {
        emit();
    }
}

/// Closes a scope from a `Drop`. While the thread unwinds, a notification that
/// panics is contained, so the unwind does not abort.
pub(crate) fn leave_from_drop() {
    if thread::panicking() {
        let _ = catch_unwind(AssertUnwindSafe(leave));
    } else {
        leave();
    }
}

/// Queues `emit` for the open scope, or runs it at once when no scope is open.
pub(crate) fn queue(emit: Emit) {
    let emit_now = SCOPE.with(|scope| {
        let mut scope = scope.borrow_mut();
        if scope.depth == 0 {
            Some(emit)
        } else {
            scope.pending.push(emit);
            None
        }
    });
    if let Some(emit) = emit_now {
        emit();
    }
}

/// Closes its scope when dropped.
struct ScopeClose;

impl Drop for ScopeClose {
    fn drop(&mut self) {
        leave_from_drop();
    }
}

/// A container membership section: the membership gate, and the scope that
/// encloses it. The gate is declared first, so it is released before the scope
/// closes (fields drop in declaration order).
pub(crate) struct MembershipSection<'a> {
    _gate: MutexGuard<'a, ()>,
    _scope: ScopeClose,
}

/// Takes a container membership gate for one section (ADR-0242).
pub(crate) fn membership_section(gate: &Mutex<()>) -> MembershipSection<'_> {
    enter();
    let scope = ScopeClose;
    MembershipSection {
        _gate: lock(gate),
        _scope: scope,
    }
}
