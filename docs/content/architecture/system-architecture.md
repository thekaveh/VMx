# 5.2. System Architecture

The system map shows how spec, builders, lifecycle, services, messaging, and
host-application code fit together. It is the fastest way to see what VMx owns
and what stays in your app.

<img src="../../assets/diagrams/system-architecture.svg" alt="VMx System Architecture" class="vmx-diagram" />

<p>
  <a href="../../assets/diagrams/system-architecture.html">Open standalone diagram</a>
  &middot;
  <a href="../../assets/diagrams/system-architecture.png">PNG</a>
</p>

The important boundary is that UI frameworks stay outside the VMx core. The
framework provides lifecycle, hierarchy, commands, services, and helpers; your
host app supplies models, view bindings, and platform-specific rendering.
