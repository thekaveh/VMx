# Lifecycle & Messaging

Lifecycle and messaging are the runtime spine of VMx. Construction transitions,
property messages, and collection events are coordinated so parent and child
trees behave predictably across flavors.

<img src="../../assets/diagrams/lifecycle-messaging.svg" alt="Lifecycle And Messaging Flow" class="vmx-diagram" />

<p>
  <a href="../../assets/diagrams/lifecycle-messaging.html">Open standalone diagram</a>
  &middot;
  <a href="../../assets/diagrams/lifecycle-messaging.png">PNG</a>
</p>

This view is most useful when you need to reason about construct/destruct
ordering, hub notifications, or how state changes propagate across a VM tree.
