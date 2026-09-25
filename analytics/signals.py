from django.db.models.signals import post_delete, post_save

from .services import increment_cache_version


def _is_event_model(sender):
    options = getattr(sender, "_meta", None)
    if options is None or options.app_label != "monitoring":
        return False
    return options.model_name in {"Event", "EventLog", "EventRecord"}


def _invalidate_after_ingestion(sender, **kwargs):
    if _is_event_model(sender):
        increment_cache_version()


def _invalidate_after_event_delete(sender, **kwargs):
    if _is_event_model(sender):
        increment_cache_version()


def connect_ingestion_signals():
    post_save.connect(
        _invalidate_after_ingestion,
        dispatch_uid="analytics.invalidate_after_event_save",
        weak=False,
    )
    post_delete.connect(
        _invalidate_after_event_delete,
        dispatch_uid="analytics.invalidate_after_event_delete",
        weak=False,
    )


def disconnect_ingestion_signals():
    post_save.disconnect(
        _invalidate_after_ingestion,
        dispatch_uid="analytics.invalidate_after_event_save",
    )
    post_delete.disconnect(
        _invalidate_after_event_delete,
        dispatch_uid="analytics.invalidate_after_event_delete",
    )


connect_ingestion_signals()
