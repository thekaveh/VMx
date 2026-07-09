use vmx::{Command, ComponentVm, MessageHub, NullDispatcher, RelayCommand, VmxResult};

fn main() -> VmxResult<()> {
    let hub = MessageHub::new();
    let dispatcher = NullDispatcher::new();
    let vm = ComponentVm::with_services("hello-rust", hub, dispatcher);
    vm.construct()?;

    let command = RelayCommand::new(|| println!("Hello from VMx Rust"));
    command.execute();

    println!("{} constructed: {}", vm.name(), vm.is_constructed());
    vm.dispose()
}
