# VMx.Notifications

A notification and confirmation hub for [VMx](https://www.nuget.org/packages/VMx),
the lifecycle-aware MVVM viewmodel framework. This package depends on `VMx`
and adds:

- `INotificationHub` and `NotificationHub`, which publish transient
  notifications and confirmation requests to whichever view hosts them;
- `NotificationVM` and `ConfirmationVM` viewmodels for presenting them;
- `ConfirmHelper` and fluent extensions that turn a confirmation into a
  command gate;
- `NullNotificationHub` for tests and headless hosts.

It is opt-in: an application that needs only viewmodels and commands uses the
`VMx` package alone.

## Documentation

- [Notification viewmodels](https://thekaveh.github.io/VMx/primitives/viewmodel-families/specialized/notification-vm/)
- [Confirmation viewmodels](https://thekaveh.github.io/VMx/primitives/viewmodel-families/specialized/confirmation-vm/)
- [Getting started with C#](https://thekaveh.github.io/VMx/getting-started/csharp/)
- [Changelog](https://github.com/thekaveh/VMx/blob/main/langs/csharp/CHANGELOG.md)
- [Source and issues](https://github.com/thekaveh/VMx)

Licensed under the [Apache License 2.0](https://github.com/thekaveh/VMx/blob/main/LICENSE).
