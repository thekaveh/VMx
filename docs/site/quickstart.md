# Quickstart

Each flavor exposes the same shape: wire a message hub and dispatcher, build a
leaf `ComponentVM`, then compose child tabs in a `CompositeVM`.

<div class="tabbed-set tabbed-alternate" data-tabs="quickstart:4">
  <input checked id="quickstart-csharp" name="quickstart" type="radio" />
  <input id="quickstart-python" name="quickstart" type="radio" />
  <input id="quickstart-typescript" name="quickstart" type="radio" />
  <input id="quickstart-swift" name="quickstart" type="radio" />
  <div class="tabbed-labels">
    <label for="quickstart-csharp">C#</label>
    <label for="quickstart-python">Python</label>
    <label for="quickstart-typescript">TypeScript</label>
    <label for="quickstart-swift">Swift</label>
  </div>
  <div class="tabbed-content">
    <div class="tabbed-block">
      <pre><code class="language-csharp">IMessageHub hub = new MessageHub();
IDispatcher dispatcher = RxDispatcher.Immediate();

var homeTab = ComponentVM<span class="vmx-code-lt"></span>TabModel<span class="vmx-code-gt"></span>.Builder()
.Name("home-tab")
.Model(new TabModel("Home"))
.Services(hub, dispatcher)
.Build();

var settingsTab = ComponentVM<span class="vmx-code-lt"></span>TabModel<span class="vmx-code-gt"></span>.Builder()
.Name("settings-tab")
.Model(new TabModel("Settings"))
.Services(hub, dispatcher)
.Build();

var tabs = CompositeVM<span class="vmx-code-lt"></span>ComponentVM<span class="vmx-code-lt"></span>TabModel<span class="vmx-code-gt"></span><span class="vmx-code-gt"></span>.Builder()
.Name("tab-bar")
.Services(hub, dispatcher)
.Children(() => [homeTab, settingsTab])
.Build();

tabs.Construct();
tabs.Current = settingsTab;</code></pre>
    </div>
    <div class="tabbed-block">
    <pre><code class="language-python">hub = MessageHub()
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
tabs.current = settings_tab</code></pre>
    </div>
    <div class="tabbed-block">
    <pre><code class="language-ts">const hub = new MessageHub();
const dispatcher = RxDispatcher.immediate();

const homeTab = ComponentVMOf.builder<span class="vmx-code-lt"></span>TabModel<span class="vmx-code-gt"></span>()
.name("home-tab")
.model({ title: "Home" })
.services(hub, dispatcher)
.build();

const settingsTab = ComponentVMOf.builder<span class="vmx-code-lt"></span>TabModel<span class="vmx-code-gt"></span>()
.name("settings-tab")
.model({ title: "Settings" })
.services(hub, dispatcher)
.build();

const tabs = CompositeVM.builder<span class="vmx-code-lt"></span>ComponentVMOf<span class="vmx-code-lt"></span>TabModel<span class="vmx-code-gt"></span><span class="vmx-code-gt"></span>()
.name("tab-bar")
.services(hub, dispatcher)
.children(() => [homeTab, settingsTab])
.build();

tabs.construct();
tabs.current = settingsTab;</code></pre>
    </div>
    <div class="tabbed-block">
    <pre><code class="language-swift">let hub = MessageHub()
let dispatcher = ImmediateDispatcher.INSTANCE

let homeTab = try ComponentVMOf<span class="vmx-code-lt"></span>TabModel<span class="vmx-code-gt"></span>.builder()
.name("home-tab")
.model(TabModel(title: "Home"))
.services(hub: hub, dispatcher: dispatcher)
.build()

let settingsTab = try ComponentVMOf<span class="vmx-code-lt"></span>TabModel<span class="vmx-code-gt"></span>.builder()
.name("settings-tab")
.model(TabModel(title: "Settings"))
.services(hub: hub, dispatcher: dispatcher)
.build()

let tabs = try CompositeVM<span class="vmx-code-lt"></span>ComponentVMOf<span class="vmx-code-lt"></span>TabModel<span class="vmx-code-gt"></span><span class="vmx-code-gt"></span>.builder()
.name("tab-bar")
.services(hub: hub, dispatcher: dispatcher)
.children { [homeTab, settingsTab] }
.build()

tabs.construct()
tabs.current = settingsTab</code></pre>
    </div>

</div>
</div>

## What This Shows

- One spec, four idiomatic surfaces.
- Builders stay immutable across flavors.
- Construction and selection semantics stay aligned even as naming changes.
