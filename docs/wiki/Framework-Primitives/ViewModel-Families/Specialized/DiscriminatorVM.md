# DiscriminatorVM

Use `DiscriminatorVM<TKey>` when one VM needs a single source of truth for an
active pane, mode, route, focus target, or modal precedence stack.

## Key Traits

- owns one active key
- emits changes only on real transitions
- supports modal open and close with LIFO restore behavior

## Related Pages

- [[FormVM|Framework-Primitives/ViewModel-Families/Specialized/FormVM]]
- [[Editor Mode & DiscriminatorVM|Examples/Editor-Mode-and-DiscriminatorVM]]
