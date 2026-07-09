# Quickstart

Each flavor exposes the same shape: wire a message hub and dispatcher, build a
leaf `ComponentVM`, then compose child tabs in a `CompositeVM`.

=== "C#"

    ```csharp
    IMessageHub hub = new MessageHub();
    IDispatcher dispatcher = RxDispatcher.Immediate();

    var homeTab = ComponentVM<TabModel>.Builder()
        .Name("home-tab")
        .Model(new TabModel("Home"))
        .Services(hub, dispatcher)
        .Build();

    var settingsTab = ComponentVM<TabModel>.Builder()
        .Name("settings-tab")
        .Model(new TabModel("Settings"))
        .Services(hub, dispatcher)
        .Build();

    var tabs = CompositeVM<ComponentVM<TabModel>>.Builder()
        .Name("tab-bar")
        .Services(hub, dispatcher)
        .Children(() => [homeTab, settingsTab])
        .Build();

    tabs.Construct();
    tabs.Current = settingsTab;
    ```

=== "Python"

    ```python
    hub = MessageHub()
    dispatcher = RxDispatcher.immediate()

    home_tab = (
        ComponentVMOf.builder()
        .name("home-tab")
        .model(TabModel("Home"))
        .services(hub, dispatcher)
        .build()
    )

    settings_tab = (
        ComponentVMOf.builder()
        .name("settings-tab")
        .model(TabModel("Settings"))
        .services(hub, dispatcher)
        .build()
    )

    tabs = (
        CompositeVM.builder()
        .name("tab-bar")
        .services(hub, dispatcher)
        .children(lambda: [home_tab, settings_tab])
        .build()
    )

    tabs.construct()
    tabs.current = settings_tab
    ```

=== "TypeScript"

    ```ts
    const hub = new MessageHub();
    const dispatcher = RxDispatcher.immediate();

    const homeTab = ComponentVMOf.builder<TabModel>()
      .name("home-tab")
      .model({ title: "Home" })
      .services(hub, dispatcher)
      .build();

    const settingsTab = ComponentVMOf.builder<TabModel>()
      .name("settings-tab")
      .model({ title: "Settings" })
      .services(hub, dispatcher)
      .build();

    const tabs = CompositeVM.builder<ComponentVMOf<TabModel>>()
      .name("tab-bar")
      .services(hub, dispatcher)
      .children(() => [homeTab, settingsTab])
      .build();

    tabs.construct();
    tabs.current = settingsTab;
    ```

=== "Swift"

    ```swift
    let hub = MessageHub()
    let dispatcher = ImmediateDispatcher.INSTANCE

    let homeTab = try ComponentVMOf<TabModel>.builder()
        .name("home-tab")
        .model(TabModel(title: "Home"))
        .services(hub: hub, dispatcher: dispatcher)
        .build()

    let settingsTab = try ComponentVMOf<TabModel>.builder()
        .name("settings-tab")
        .model(TabModel(title: "Settings"))
        .services(hub: hub, dispatcher: dispatcher)
        .build()

    let tabs = try CompositeVM<ComponentVMOf<TabModel>>.builder()
        .name("tab-bar")
        .services(hub: hub, dispatcher: dispatcher)
        .children { [homeTab, settingsTab] }
        .build()

    try tabs.construct()
    tabs.current = settingsTab
    ```

=== "Rust"

    ```rust
    use vmx::{ComponentVm, CompositeVm, MessageHub, NullDispatcher, VmxResult};

    #[derive(Clone, PartialEq)]
    struct TabModel {
        title: String,
    }

    fn main() -> VmxResult<()> {
        let hub = MessageHub::new();
        let dispatcher = NullDispatcher::new();

        let home_tab = ComponentVm::with_model(
            "home-tab",
            TabModel { title: "Home".to_string() },
            hub.clone(),
            dispatcher,
        );
        let settings_tab = ComponentVm::with_model(
            "settings-tab",
            TabModel { title: "Settings".to_string() },
            hub.clone(),
            dispatcher,
        );

        let tabs = CompositeVm::with_services("tab-bar", hub, dispatcher);
        tabs.add(home_tab.clone())?;
        tabs.add(settings_tab.clone())?;

        tabs.construct()?;
        tabs.select_component(&settings_tab)
    }
    ```

## What This Shows

- One spec and five idiomatic source surfaces.
- Builders/direct construction stay idiomatic per flavor.
- Construction and selection semantics stay aligned even as naming changes.
