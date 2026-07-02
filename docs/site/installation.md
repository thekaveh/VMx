# Installation

VMx has four source flavors. The source tree implements v3.1.0 for C#,
Python, TypeScript, and Swift. Public package availability can lag the source
tree; check the flavor README and registry before pinning a release.

| Flavor     | Source tree | Public package status           |
| ---------- | ----------- | ------------------------------- |
| C#         | v3.1.0      | NuGet package not published yet |
| Python     | v3.1.0      | `vmx` latest published: 2.6.1   |
| TypeScript | v3.1.0      | npm package not published yet   |
| Swift      | v3.1.0      | SwiftPM tag not published yet   |

<div class="tabbed-set tabbed-alternate" data-tabs="install:4">
  <input checked id="install-csharp" name="install" type="radio" />
  <input id="install-python" name="install" type="radio" />
  <input id="install-typescript" name="install" type="radio" />
  <input id="install-swift" name="install" type="radio" />
  <div class="tabbed-labels">
    <label for="install-csharp">C#</label>
    <label for="install-python">Python</label>
    <label for="install-typescript">TypeScript</label>
    <label for="install-swift">Swift</label>
  </div>
  <div class="tabbed-content">
    <div class="tabbed-block">
      <pre><code class="language-bash">dotnet add package VMx</code></pre>
    </div>
    <div class="tabbed-block">
      <pre><code class="language-bash">pip install vmx
# or
uv add vmx</code></pre>
    </div>
    <div class="tabbed-block">
      <pre><code class="language-bash">npm install @thekaveh/vmx rxjs</code></pre>
    </div>
    <div class="tabbed-block">
      <pre><code class="language-swift">.package(url: "https://github.com/thekaveh/VMx.git", from: "3.1.0")</code></pre>
    </div>
  </div>
</div>

## Notes

- C# uses `System.Reactive`.
- Python uses `reactivex`.
- TypeScript uses `rxjs`.
- Swift uses `Combine`.
