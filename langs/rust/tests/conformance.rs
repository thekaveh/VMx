mod conformance {
    mod aggregate_change_stream;
    mod aggregate_vm;
    mod async_resource_completion;
    mod async_resource_vm;
    mod async_value;
    mod auto_construct_during_constructing;
    mod background_child_settle;
    mod bounded_wait;
    mod builder_population;
    mod builders;
    mod capabilities;
    mod child_transition_helper;
    mod collection_failing_local_subscriber;
    mod collection_lookup_clones;
    mod collections;
    mod command_decorators;
    mod command_ext;
    mod commands;
    mod component_vm;
    mod composite_selection_disposal;
    mod composite_vm;
    mod confirmation_async_inner;
    mod container_disposal_wait_cycle;
    mod container_hook_disposal;
    mod container_members;
    mod derived_properties;
    mod dialogs;
    mod dictionary_hash_lookup;
    mod dictionary_key_view_order;
    mod dictionary_key_views_read_only;
    mod dictionary_remove_replace_positions;
    mod discriminator;
    mod disposed_child_walks;
    mod drop_panic_publication;
    mod drop_reentry;
    mod expandable;
    mod filtered_composite;
    mod form_approval_admission;
    mod form_approval_completion;
    mod form_approval_subscription;
    mod form_approval_update_queue;
    mod form_failure_atomic_updates;
    mod form_model_hub_publication;
    mod form_nested_update_notifications;
    // Every case here observes the wait-for graph through a test seam.
    #[cfg(feature = "test-seams")]
    mod form_publication_wait_cycle;
    mod form_reader_consistency;
    mod form_unscoped_delivery;
    mod forms;
    mod forwarding;
    mod group_vm;
    mod hierarchical;
    mod hierarchical_batch;
    mod hierarchical_disposed_node;
    mod hub_collection_changes;
    mod hub_disposal_during_publication;
    // Every case here observes the wait-for graph through a test seam.
    #[cfg(feature = "test-seams")]
    mod hub_membership_wait_cycle;
    mod inline_dispose_cascade;
    mod item_clone_reentry;
    mod leaf_hook_disposal;
    mod lifecycle;
    mod localization;
    mod message_hub;
    mod message_recorder;
    mod modeled_crud;
    // Every case here observes the wait-for graph through a test seam.
    #[cfg(feature = "test-seams")]
    mod multi_dictionary_delivery_wait_cycle;
    mod multi_dictionary_events;
    // The notifications sub-package is a Cargo feature (ADR-0211).
    #[cfg(feature = "notifications")]
    mod notifications;
    mod null_services;
    mod observable_list_events;
    mod observable_list_replace_all;
    mod owned_resources;
    mod paged_composition_notifications;
    mod post_dispose_modeled_assignment;
    mod property_change;
    // Every case here observes the wait-for graph through a test seam.
    #[cfg(feature = "test-seams")]
    mod recompute_wait_cycle;
    mod reconstruct_command_parity;
    mod reconstruct_settle;
    mod reverse_destruct_order;
    mod search_filter;
    mod selection_transactions;
    mod stream_wait_cycle;
    mod subscribe_value;
    mod threading;
    mod token_clone_reentry;
    mod token_load_terminal;
    mod token_refresh_cursor;
    mod tree_selection;
    mod tree_utils;
    mod user_equality_reentry;
    mod value_stream;
    mod vm_collection_move;
}
