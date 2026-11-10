//! A fixed-slot population that its preflight refuses disposes the fresh
//! candidates that nobody owns (spec/08 §2 and §4, ADR-0224, #1324).

use std::sync::{
    atomic::{AtomicBool, AtomicUsize, Ordering},
    mpsc, Arc, Mutex,
};
use std::time::Duration;

use vmx::{ConstructionStatus, MessageHub, NullDispatcher, ParentHandle, VmNode, VmxError};

type TextVm = vmx::ComponentVm<&'static str>;

fn text(name: &'static str) -> TextVm {
    TextVm::with_model(name, name, MessageHub::new(), NullDispatcher::new())
}

/// A component that a constructed composite owns.
fn owned(name: &'static str) -> (TextVm, vmx::CompositeVm<TextVm>) {
    let component = text(name);
    let owner = vmx::CompositeVm::new("owner");
    owner.add(component.clone()).unwrap();
    owner.construct().unwrap();
    assert_eq!(component.status(), ConstructionStatus::Constructed);
    (component, owner)
}

/// AGG-008 — a refused `construct()` disposes the fresh candidate, keeps the
/// owned candidate's status and parent, and leaves both slots empty.
#[test]
fn refused_construct_disposes_the_unowned_candidates() {
    let fresh = text("fresh");
    let (borrowed, owner) = owned("borrowed");
    let first = fresh.clone();
    let second = borrowed.clone();
    let aggregate = vmx::AggregateVm2::builder()
        .name("aggregate")
        .services(MessageHub::new(), NullDispatcher::new())
        .component_1(move || first.clone())
        .component_2(move || second.clone())
        .build()
        .unwrap();

    assert_eq!(aggregate.construct(), Err(VmxError::InconsistentParent));

    assert_eq!(fresh.status(), ConstructionStatus::Disposed);
    assert_eq!(borrowed.status(), ConstructionStatus::Constructed);
    assert_eq!(borrowed.parent_id(), Some(owner.id()));
    assert_eq!(owner.items(), vec![borrowed]);
    assert!(aggregate.component_1().is_none());
    assert!(aggregate.component_2().is_none());
}

/// AGG-008 — a refused `reconstruct()` keeps the old slots and parent links
/// and disposes the fresh replacement candidate.
#[test]
fn refused_reconstruct_disposes_the_fresh_candidates_and_keeps_the_old_slots() {
    let first = text("first");
    let second = text("second");
    let replacement = text("replacement");
    let (borrowed, owner) = owned("borrowed");
    let first_calls = Arc::new(AtomicUsize::new(0));
    let second_calls = Arc::new(AtomicUsize::new(0));
    let (first_counter, second_counter) = (Arc::clone(&first_calls), Arc::clone(&second_calls));
    let (original_first, next_first) = (first.clone(), replacement.clone());
    let (original_second, next_second) = (second.clone(), borrowed.clone());
    let aggregate = vmx::AggregateVm2::builder()
        .name("aggregate")
        .services(MessageHub::new(), NullDispatcher::new())
        .component_1(move || {
            if first_counter.fetch_add(1, Ordering::SeqCst) == 0 {
                original_first.clone()
            } else {
                next_first.clone()
            }
        })
        .component_2(move || {
            if second_counter.fetch_add(1, Ordering::SeqCst) == 0 {
                original_second.clone()
            } else {
                next_second.clone()
            }
        })
        .build()
        .unwrap();
    aggregate.construct().unwrap();

    assert_eq!(aggregate.reconstruct(), Err(VmxError::InconsistentParent));

    assert_eq!(aggregate.component_1(), Some(first.clone()));
    assert_eq!(aggregate.component_2(), Some(second.clone()));
    assert_eq!(first.parent_id(), Some(aggregate.id()));
    assert_eq!(second.parent_id(), Some(aggregate.id()));
    assert_eq!(first.status(), ConstructionStatus::Destructed);
    assert_eq!(second.status(), ConstructionStatus::Destructed);
    assert_eq!(replacement.status(), ConstructionStatus::Disposed);
    assert_eq!(replacement.parent_id(), None);
    assert_eq!(borrowed.status(), ConstructionStatus::Constructed);
    assert_eq!(borrowed.parent_id(), Some(owner.id()));
}

macro_rules! assert_last_slot_refusal_disposes_fresh_candidates {
    ($builder:expr, $last:ident, $( $slot:ident ),+ $(,)?) => {{
        let (borrowed, owner) = owned("borrowed");
        let mut fresh = Vec::new();
        let builder = $builder;
        $(
            let candidate = text(stringify!($slot));
            fresh.push(candidate.clone());
            let builder = builder.$slot(move || candidate.clone());
        )+
        let last = borrowed.clone();
        let aggregate = builder.$last(move || last.clone()).build().unwrap();

        assert_eq!(aggregate.construct(), Err(VmxError::InconsistentParent));

        for candidate in fresh {
            assert_eq!(candidate.status(), ConstructionStatus::Disposed);
            assert_eq!(candidate.parent_id(), None);
        }
        assert_eq!(borrowed.status(), ConstructionStatus::Constructed);
        assert_eq!(borrowed.parent_id(), Some(owner.id()));
        assert!(aggregate.$last().is_none());
    }};
}

/// AGG-008 — arities two through six dispose every fresh candidate when the
/// last factory returns an owned component.
#[test]
fn refused_construct_disposes_fresh_candidates_for_arities_two_through_six() {
    assert_last_slot_refusal_disposes_fresh_candidates!(
        vmx::AggregateVm2::builder()
            .name("aggregate-2")
            .services(MessageHub::new(), NullDispatcher::new()),
        component_2,
        component_1,
    );
    assert_last_slot_refusal_disposes_fresh_candidates!(
        vmx::AggregateVm3::builder()
            .name("aggregate-3")
            .services(MessageHub::new(), NullDispatcher::new()),
        component_3,
        component_1,
        component_2,
    );
    assert_last_slot_refusal_disposes_fresh_candidates!(
        vmx::AggregateVm4::builder()
            .name("aggregate-4")
            .services(MessageHub::new(), NullDispatcher::new()),
        component_4,
        component_1,
        component_2,
        component_3,
    );
    assert_last_slot_refusal_disposes_fresh_candidates!(
        vmx::AggregateVm5::builder()
            .name("aggregate-5")
            .services(MessageHub::new(), NullDispatcher::new()),
        component_5,
        component_1,
        component_2,
        component_3,
        component_4,
    );
    assert_last_slot_refusal_disposes_fresh_candidates!(
        vmx::AggregateVm6::builder()
            .name("aggregate-6")
            .services(MessageHub::new(), NullDispatcher::new()),
        component_6,
        component_1,
        component_2,
        component_3,
        component_4,
        component_5,
    );
}

/// Two slots that return one fresh component fail the duplicate check, and
/// the cleanup disposes that component once.
#[test]
fn duplicate_fresh_candidate_is_disposed_once() {
    let shared = text("shared");
    let disposals = Arc::new(AtomicUsize::new(0));
    let counter = Arc::clone(&disposals);
    shared.on_dispose(move || {
        counter.fetch_add(1, Ordering::SeqCst);
        Ok(())
    });
    let (first, second) = (shared.clone(), shared.clone());
    let aggregate = vmx::AggregateVm2::builder()
        .name("aggregate")
        .services(MessageHub::new(), NullDispatcher::new())
        .component_1(move || first.clone())
        .component_2(move || second.clone())
        .build()
        .unwrap();

    assert_eq!(aggregate.construct(), Err(VmxError::DuplicateChild));

    assert_eq!(shared.status(), ConstructionStatus::Disposed);
    assert_eq!(disposals.load(Ordering::SeqCst), 1);
}

/// A candidate disposal failure does not replace the preflight failure.
#[test]
fn candidate_disposal_failure_keeps_the_preflight_failure() {
    let fresh = text("fresh");
    fresh.on_dispose(|| Err(VmxError::Other("candidate disposal failed".to_string())));
    let (borrowed, _owner) = owned("borrowed");
    let (first, second) = (fresh.clone(), borrowed.clone());
    let aggregate = vmx::AggregateVm2::builder()
        .name("aggregate")
        .services(MessageHub::new(), NullDispatcher::new())
        .component_1(move || first.clone())
        .component_2(move || second.clone())
        .build()
        .unwrap();

    assert_eq!(aggregate.construct(), Err(VmxError::InconsistentParent));
    assert_eq!(fresh.status(), ConstructionStatus::Disposed);
}

#[derive(Clone)]
struct BlockingNode {
    inner: vmx::ComponentVm,
    block_once: Arc<AtomicBool>,
    entered: mpsc::Sender<()>,
    release: Arc<Mutex<mpsc::Receiver<()>>>,
}

impl PartialEq for BlockingNode {
    fn eq(&self, other: &Self) -> bool {
        self.inner == other.inner
    }
}

impl VmNode for BlockingNode {
    fn id(&self) -> usize {
        self.inner.id()
    }

    fn construct(&self) -> vmx::VmxResult<()> {
        self.inner.construct()
    }

    fn destruct(&self) -> vmx::VmxResult<()> {
        self.inner.destruct()
    }

    fn dispose(&self) -> vmx::VmxResult<()> {
        self.inner.dispose()
    }

    fn status(&self) -> ConstructionStatus {
        self.inner.status()
    }

    fn set_parent_id(&self, parent_id: Option<usize>) {
        self.inner.set_parent_id(parent_id);
    }

    fn parent_id(&self) -> Option<usize> {
        let parent_id = self.inner.parent_id();
        if self.block_once.swap(false, Ordering::AcqRel) {
            self.entered.send(()).unwrap();
            self.release.lock().unwrap().recv().unwrap();
        }
        parent_id
    }

    fn set_parent_handle(&self, parent: Option<ParentHandle>) {
        self.inner.set_parent_handle(parent);
    }

    fn parent_handle(&self) -> Option<ParentHandle> {
        self.inner.parent_handle()
    }
}

/// A candidate that another ownership transaction holds belongs to that
/// transaction, so the refused population does not dispose it.
#[test]
fn candidate_held_by_another_transaction_is_not_disposed() {
    let (entered_send, entered) = mpsc::channel();
    let (release, release_receive) = mpsc::channel();
    let shared = BlockingNode {
        inner: vmx::ComponentVm::new("shared"),
        block_once: Arc::new(AtomicBool::new(true)),
        entered: entered_send,
        release: Arc::new(Mutex::new(release_receive)),
    };
    let holder_child = shared.clone();
    let holder = std::thread::spawn(move || vmx::AggregateVm1::try_new("holder", holder_child));
    entered.recv_timeout(Duration::from_secs(5)).unwrap();

    let candidate = shared.clone();
    let refused = vmx::AggregateVm1::builder()
        .name("refused")
        .services(MessageHub::new(), NullDispatcher::new())
        .component_1(move || candidate.clone())
        .build()
        .unwrap();
    let result = refused.construct();
    release.send(()).unwrap();
    let holder = holder.join().unwrap().unwrap();

    assert_eq!(result, Err(VmxError::OwnershipTransactionInProgress));
    assert_ne!(shared.status(), ConstructionStatus::Disposed);
    assert_eq!(shared.parent_id(), Some(holder.id()));
    assert!(refused.component_1().is_none());
}
