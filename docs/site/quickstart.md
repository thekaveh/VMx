# Quickstart

Each flavor exposes the same shape: wire a message hub and dispatcher, build a
leaf `ComponentVM`, then compose child tabs in a `CompositeVM`.

=== "C#"

````
```csharp
using VMx.Components;
using VMx.Composites;
using VMx.Services;

public record UserModel(string Name);
public record TabModel(string Title);

IMessageHub hub = new MessageHub();
IDispatcher dispatcher = RxDispatcher.Immediate();

var userVm = ComponentVM<UserModel>.Builder()
    .Name("user-card")
    .Model(new UserModel("Alice"))
    .Services(hub, dispatcher)
    .ModeledHinter(m => m.Name)
    .Build();

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

userVm.Construct();
tabs.Construct();
tabs.Current = settingsTab;
```
````

=== "Python"

````
```python
from dataclasses import dataclass

from vmx.components import ComponentVMOf
from vmx.composites import CompositeVM
from vmx.services import MessageHub, RxDispatcher

@dataclass(frozen=True)
class UserModel:
    name: str

@dataclass(frozen=True)
class TabModel:
    title: str

hub = MessageHub()
dispatcher = RxDispatcher.immediate()

user_vm = (
    ComponentVMOf.builder()
    .name("user-card")
    .model(UserModel("Alice"))
    .services(hub, dispatcher)
    .modeled_hinter(lambda m: m.name)
    .build()
)

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

user_vm.construct()
tabs.construct()
tabs.current = settings_tab
```
````

=== "TypeScript"

````
```ts
import {
  ComponentVMOf,
  CompositeVM,
  MessageHub,
  RxDispatcher,
} from "@thekaveh/vmx";

interface UserModel { name: string; }
interface TabModel { title: string; }

const hub = new MessageHub();
const dispatcher = RxDispatcher.immediate();

const userVM = ComponentVMOf.builder<UserModel>()
  .name("user-card")
  .model({ name: "Alice" })
  .services(hub, dispatcher)
  .modeledHinter((m) => m.name)
  .build();

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

userVM.construct();
tabs.construct();
tabs.current = settingsTab;
```
````

=== "Swift"

````
```swift
import VMx

struct UserModel: Equatable {
    let name: String
}

struct TabModel: Equatable {
    let title: String
}

let hub = MessageHub()
let dispatcher = ImmediateDispatcher.INSTANCE

let userVM = try ComponentVMOf<UserModel>.builder()
    .name("user-card")
    .model(UserModel(name: "Alice"))
    .services(hub: hub, dispatcher: dispatcher)
    .modeledHinter { $0.name }
    .build()

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

userVM.construct()
tabs.construct()
tabs.current = settingsTab
```
````

## What This Shows

- One spec, four idiomatic surfaces.
- Builders stay immutable across flavors.
- Construction and selection semantics stay aligned even as naming changes.
