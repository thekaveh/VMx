use vmx::{
    Command, ComponentVm, CompositeVm, FilteredCompositeVm, MessageHub, NullDispatcher,
    RelayCommand, VmxResult,
};

fn main() -> VmxResult<()> {
    let hub = MessageHub::new();
    let dispatcher = NullDispatcher::new();
    let notes = vec![
        ComponentVm::with_model(
            "rust-roadmap",
            "Rust flavor parity",
            hub.clone(),
            dispatcher,
        ),
        ComponentVm::with_model(
            "release-plan",
            "Publish package channels",
            hub.clone(),
            dispatcher,
        ),
        ComponentVm::with_model("docs", "Refresh diagrams and wiki", hub.clone(), dispatcher),
    ];

    let notes_vm = CompositeVm::builder()
        .name("notes")
        .services(hub, dispatcher)
        .children({
            let notes = notes.clone();
            move || notes.clone()
        })
        .current(|items| items.first().cloned())
        .build()?;
    notes_vm.construct()?;

    let rust_notes = FilteredCompositeVm::new(notes_vm.clone(), |note| {
        note.model().to_lowercase().contains("rust")
    });

    let command = RelayCommand::new(|| println!("Hello from VMx Rust"));
    command.execute();

    println!("notes constructed with {} notes", notes_vm.len());
    println!(
        "current: {}",
        notes_vm
            .current()
            .map(|note| note.name())
            .unwrap_or_default()
    );
    println!("rust search matches: {}", rust_notes.visible_count());
    notes_vm.dispose()
}
