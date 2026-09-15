from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Literal, Mapping, Protocol
from uuid import UUID, uuid4

from django.apps import apps
from django.db import transaction
from django.db.models import Model, QuerySet
from django.utils.module_loading import import_string

from bloomerp.celery.utils import is_celery_available, parse_cron_schedule
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.utils.json_serialization import make_json_safe
from bloomerp.utils.realtime import NotificationPayload, ToastPayload, send_user_inbox_message

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
    from bloomerp.models.communication.inbox.inbox_item import InboxItem


class FolderQuerySetResolver(Protocol):
    def __call__(self, *args, **kwargs) -> QuerySet["InboxFolder"]: ...


class InboxSourceHandler(Protocol):
    def __call__(
        self,
        folders: QuerySet["InboxFolder"],
        *args,
        **kwargs,
    ) -> "InboxSourceExecutionResult": ...


CallableReference = Callable[..., Any] | str
FolderResolverReference = FolderQuerySetResolver | str
HandlerReference = InboxSourceHandler | str


def resolve_callable(
    value: CallableReference,
    *,
    field_name: str,
    source_key: str,
) -> Callable[..., Any]:
    resolved = import_string(value) if isinstance(value, str) else value
    if not callable(resolved):
        raise TypeError(
            f"{field_name} for inbox source {source_key!r} must resolve to a callable."
        )
    return resolved


@dataclass(frozen=True, kw_only=True)
class InboxSourceDelivery:
    folder: "InboxFolder"
    items: tuple["InboxItem", ...]


@dataclass(frozen=True, kw_only=True)
class InboxSourceExecutionResult:
    outcome: Literal["completed", "skipped"] = "completed"
    deliveries: tuple[InboxSourceDelivery, ...] = ()
    reason: str | None = None
    metrics: Mapping[str, int | float | str] = field(default_factory=dict)

    @property
    def delivery_count(self) -> int:
        return len(self.deliveries)

    @property
    def item_count(self) -> int:
        return sum(len(delivery.items) for delivery in self.deliveries)


@dataclass(frozen=True, kw_only=True)
class InboxSourceReceipt:
    source_key: str
    execution_id: UUID
    state: Literal["scheduled", "completed"]
    result: InboxSourceExecutionResult | None = None


@dataclass(frozen=True, kw_only=True)
class BaseInboxSource:
    key: str
    folder_qs_resolver: FolderResolverReference
    handler: HandlerReference

    def resolve_folder_qs_resolver(self) -> FolderQuerySetResolver:
        return resolve_callable(
            self.folder_qs_resolver,
            field_name="folder_qs_resolver",
            source_key=self.key,
        )

    def resolve_handler(self) -> InboxSourceHandler:
        return resolve_callable(
            self.handler,
            field_name="handler",
            source_key=self.key,
        )


@dataclass(frozen=True, kw_only=True)
class InboxJobSource(BaseInboxSource):
    schedule: str


@dataclass(frozen=True, kw_only=True)
class InboxEventSource(BaseInboxSource):
    run_async: bool = True


@dataclass(frozen=True, kw_only=True)
class InboxSignalSource(BaseInboxSource):
    signal: "Signal | str"
    dispatch_uid: str
    sender: type[Model] | str | None = None
    predicate: CallableReference | None = None
    run_async: bool = True

    def resolve_predicate(self) -> Callable[..., Any] | None:
        if self.predicate is None:
            return None
        return resolve_callable(
            self.predicate,
            field_name="predicate",
            source_key=self.key,
        )


@dataclass(frozen=True)
class RegisteredInboxSource:
    folder_type: str
    source: BaseInboxSource
    origin: str


class InboxSourceRegistry:
    """Runtime registry compiled from folder defaults and module extensions."""

    _sources: ClassVar[dict[str, RegisteredInboxSource]] = {}
    _defaults_loaded: ClassVar[bool] = False
    _loaded_default_sources: ClassVar[set[tuple[str, str]]] = set()
    _signals_connected: ClassVar[bool] = False
    _connected_signal_sources: ClassVar[set[str]] = set()

    @classmethod
    def register(
        cls,
        *,
        folder_type: str,
        source: BaseInboxSource,
        origin: str,
    ) -> None:
        if not source.key:
            raise ValueError("Inbox source keys cannot be empty.")
        if source.key in cls._sources:
            existing = cls._sources[source.key]
            raise ValueError(
                f"Inbox source {source.key!r} is already registered by "
                f"{existing.origin!r}."
            )

        cls._sources[source.key] = RegisteredInboxSource(
            folder_type=folder_type,
            source=source,
            origin=origin,
        )

    @classmethod
    def register_source(
        cls,
        source: BaseInboxSource,
        *,
        folder_type: str,
        origin: str = "runtime",
    ) -> None:
        """Compatibility-friendly API for modules that add non-default sources."""
        cls.register(folder_type=folder_type, source=source, origin=origin)

    @classmethod
    def load_defaults(cls) -> None:
        from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY

        for definition in INBOX_FOLDER_REGISTRY.values():
            for source in definition.default_sources or ():
                source_identity = (definition.key, source.key)
                if source_identity in cls._loaded_default_sources:
                    continue
                cls.register(
                    folder_type=definition.key,
                    source=source,
                    origin=f"InboxFolderRegistry.{definition.key}",
                )
                cls._loaded_default_sources.add(source_identity)

        cls._defaults_loaded = True

    @classmethod
    def get_by_key(cls, key: str) -> RegisteredInboxSource:
        cls.load_defaults()
        try:
            return cls._sources[key]
        except KeyError as error:
            raise KeyError(f"Unknown inbox source {key!r}.") from error

    @classmethod
    def all(cls) -> tuple[RegisteredInboxSource, ...]:
        cls.load_defaults()
        return tuple(cls._sources.values())

    @classmethod
    def for_folder(cls, folder_type: str) -> tuple[RegisteredInboxSource, ...]:
        return tuple(
            registered
            for registered in cls.all()
            if registered.folder_type == folder_type
        )

    @classmethod
    def validate(cls) -> None:
        for registered in cls.all():
            source = registered.source
            source.resolve_folder_qs_resolver()
            source.resolve_handler()

            if isinstance(source, InboxJobSource):
                parse_cron_schedule(source.schedule, source_key=source.key)

            if isinstance(source, InboxSignalSource):
                _resolve_signal(source)
                _resolve_signal_sender(source)
                source.resolve_predicate()

    @classmethod
    def connect_signals(cls) -> None:
        for registered in cls.all():
            source = registered.source
            if not isinstance(source, InboxSignalSource):
                continue
            if source.key in cls._connected_signal_sources:
                continue

            signal = _resolve_signal(source)
            signal.connect(
                partial(_receive_inbox_source_signal, source_key=source.key),
                sender=_resolve_signal_sender(source),
                dispatch_uid=source.dispatch_uid,
                weak=False,
            )
            cls._connected_signal_sources.add(source.key)

        cls._signals_connected = True

    @classmethod
    def reset(cls) -> None:
        """Clear registry state. Intended for isolated tests."""
        cls._sources.clear()
        cls._defaults_loaded = False
        cls._loaded_default_sources.clear()
        cls._signals_connected = False
        cls._connected_signal_sources.clear()


def _resolve_signal(source: InboxSignalSource) -> "Signal":
    signal = import_string(source.signal) if isinstance(source.signal, str) else source.signal
    if not hasattr(signal, "connect"):
        raise TypeError(f"signal for inbox source {source.key!r} must be a Django signal.")
    return signal


def _resolve_signal_sender(source: InboxSignalSource) -> type[Model] | None:
    sender = import_string(source.sender) if isinstance(source.sender, str) else source.sender
    if sender is not None and not isinstance(sender, type):
        raise TypeError(f"sender for inbox source {source.key!r} must resolve to a type.")
    return sender


def _serialize_source_value(value: Any) -> Any:
    if isinstance(value, Model):
        return {"__model__": value._meta.label_lower, "pk": value.pk}
    if isinstance(value, type) and issubclass(value, Model):
        return {"__model_class__": value._meta.label_lower}
    if isinstance(value, dict):
        return {str(key): _serialize_source_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize_source_value(item) for item in value]
    return make_json_safe(value)


def _deserialize_source_value(value: Any) -> Any:
    if isinstance(value, dict):
        if model_label := value.get("__model__"):
            model = apps.get_model(model_label)
            return model.objects.filter(pk=value.get("pk")).first() if model else None
        if model_label := value.get("__model_class__"):
            return apps.get_model(model_label)
        return {key: _deserialize_source_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deserialize_source_value(item) for item in value]
    return value


def execute_registered_source(
    key: str,
    *args,
    **kwargs,
) -> InboxSourceExecutionResult:
    """Executes a registered source

    Args:
        key (str): source key
        *args: positional arguments to pass to the source handler
        **kwargs: keyword arguments to pass to the source handler
        
        
    Raises:
        TypeError: if the handler does not return an InboxSourceExecutionResult
        TypeError: if the handler returns an invalid delivery

    Returns:
        InboxSourceExecutionResult: Execution result of the source handler
    """
    registered = InboxSourceRegistry.get_by_key(key)
    source = registered.source
    folders = source.resolve_folder_qs_resolver()(*args, **kwargs)
    result = source.resolve_handler()(folders, *args, **kwargs)
    if not isinstance(result, InboxSourceExecutionResult):
        raise TypeError(
            f"Handler for inbox source {key!r} must return "
            "InboxSourceExecutionResult."
        )

    recipient_items: dict[int, list["InboxItem"]] = {}
    for delivery in result.deliveries:
        if not isinstance(delivery, InboxSourceDelivery):
            raise TypeError(
                f"Handler for inbox source {key!r} returned an invalid delivery."
            )
        for recipient in delivery.folder.get_recipients():
            recipient_items.setdefault(recipient.pk, []).extend(delivery.items)
    
    notification_counts = Inbox.get_unread_count_for_users(
        list(recipient_items.keys())
    )
    for recipient_id, items in recipient_items.items():
        send_user_inbox_message(
            recipient_id,
            payload=NotificationPayload(
                notification_count=notification_counts.get(str(recipient_id), 0),
                toast_payload=ToastPayload(
                    message_type="info",
                    message=(
                        items[0].snippet or items[0].title
                        if len(items) == 1
                        else f"You have {len(items)} new inbox items."
                    )
                )
            )
        )

    return result


def _dispatch_source(
    source: InboxEventSource | InboxSignalSource,
    *args,
    **kwargs,
) -> InboxSourceReceipt:
    """Dispatches the source by executing it

    Args:
        source (InboxEventSource | InboxSignalSource): the registered inbox source

    Returns:
        InboxSourceReceipt: the result
    """
    execution_id = uuid4()
    if source.run_async and is_celery_available():
        from bloomerp.celery.tasks.inbox_source_task import execute_inbox_source_task

        serialized_args = _serialize_source_value(args)
        serialized_kwargs = _serialize_source_value(kwargs)
        transaction.on_commit(
            partial(
                execute_inbox_source_task.apply_async,
                args=[
                    source.key,
                    serialized_args,
                    serialized_kwargs,
                    str(execution_id),
                ],
                task_id=str(execution_id),
            )
        )
        return InboxSourceReceipt(
            source_key=source.key,
            execution_id=execution_id,
            state="scheduled",
        )
    else:
        return InboxSourceReceipt(
            source_key=source.key,
            execution_id=execution_id,
            state="completed",
            result=execute_registered_source(source.key, *args, **kwargs),
        )


def publish_event(
    key: str,
    *args,
    **kwargs,
) -> InboxSourceReceipt:
    """Publishes an event

    Args:
        key (str): the event source key

    Raises:
        TypeError: inbox source key not an event

    Returns:
        InboxSourceReceipt: the event receipt
    """
    registered = InboxSourceRegistry.get_by_key(key)
    source = registered.source
    if not isinstance(source, InboxEventSource):
        raise TypeError(f"Inbox source {key!r} is not an event source.")
    return _dispatch_source(source, *args, **kwargs)


def _receive_inbox_source_signal(*args, source_key: str, **kwargs) -> None:
    registered = InboxSourceRegistry.get_by_key(source_key)
    source = registered.source
    if not isinstance(source, InboxSignalSource):
        raise TypeError(f"Inbox source {source_key!r} is not a signal source.")

    predicate = source.resolve_predicate()
    if predicate is not None and not predicate(*args, **kwargs):
        return
    _dispatch_source(source, *args, **kwargs)


def synchronize_job_schedules() -> None:
    from django.conf import settings
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    active_names: set[str] = set()
    for registered in InboxSourceRegistry.all():
        source = registered.source
        if not isinstance(source, InboxJobSource):
            continue

        cron_kwargs = parse_cron_schedule(source.schedule, source_key=source.key)
        cron_kwargs["timezone"] = settings.TIME_ZONE
        crontab, _ = CrontabSchedule.objects.get_or_create(**cron_kwargs)
        task_name = f"bloomerp.inbox_source.{source.key}"
        active_names.add(task_name)
        PeriodicTask.objects.update_or_create(
            name=task_name,
            defaults={
                "task": "bloomerp.celery.tasks.inbox_source_task.execute_inbox_source_task",
                "crontab": crontab,
                "interval": None,
                "solar": None,
                "clocked": None,
                "args": json.dumps([source.key]),
                "enabled": True,
                "description": f"Scheduled inbox source: {source.key}",
            },
        )

    PeriodicTask.objects.filter(name__startswith="bloomerp.inbox_source.").exclude(
        name__in=active_names
    ).delete()
