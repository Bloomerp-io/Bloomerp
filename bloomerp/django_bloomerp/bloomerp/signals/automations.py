"""Setup signals for automations."""

from collections import defaultdict
from typing import Iterable

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete, post_save
from bloomerp.models.automation.workflow_node import WorkflowNode
from bloomerp.services.workflow_services import run_workflow

_SIGNALS_INITIALIZED = False
_WORKFLOW_NODE_SIGNALS_CONNECTED = False
_REGISTERED_HANDLERS: dict[tuple[str, int], tuple[object, object]] = {}


def _normalize_content_type_id(value) -> int | None:
	if value in (None, ""):
		return None
	try:
		return int(value)
	except (TypeError, ValueError):
		return None


def _group_triggers_by_content_type(triggers: Iterable[WorkflowNode]) -> dict[int, list[WorkflowNode]]:
	grouped: dict[int, list[WorkflowNode]] = defaultdict(list)
	for trigger in triggers:
		params = (trigger.config or {}).get("parameters", {})
		content_type_id = _normalize_content_type_id(params.get("content_type_id"))
		if content_type_id is None:
			continue
		grouped[content_type_id].append(trigger)
	return grouped


def _build_trigger_data(event: str, sender, instance, **kwargs) -> dict:
	return {
		"event": event,
		"sender": sender,
		"instance": instance,
		"data": kwargs,
	}


def _create_handler(event: str, triggers: list[WorkflowNode]):
	def _handler(sender, instance, **kwargs):
		created = kwargs.get("created")
		if event == "create" and created is False:
			return
		if event == "update" and created is True:
			return

		trigger_data = _build_trigger_data(event, sender, instance, **kwargs)
		for trigger in triggers:
			run_workflow(trigger.workflow, trigger_data)

	return _handler


def _disconnect_registered_handlers() -> None:
	for (event, content_type_id), (handler, sender) in _REGISTERED_HANDLERS.items():
		dispatch_uid = f"bloomerp_automation_{event}_{content_type_id}"
		if event in ("create", "update"):
			post_save.disconnect(handler, sender=sender, dispatch_uid=dispatch_uid)
		else:
			post_delete.disconnect(handler, sender=sender, dispatch_uid=dispatch_uid)
	_REGISTERED_HANDLERS.clear()


def _refresh_automation_signals(*args, **kwargs) -> None:
	setup_automation_signals(refresh=True)


def _connect_workflow_node_signals() -> None:
	global _WORKFLOW_NODE_SIGNALS_CONNECTED
	if _WORKFLOW_NODE_SIGNALS_CONNECTED:
		return

	post_save.connect(
		_refresh_automation_signals,
		sender=WorkflowNode,
		dispatch_uid="bloomerp_refresh_automation_signals_save",
	)
	post_delete.connect(
		_refresh_automation_signals,
		sender=WorkflowNode,
		dispatch_uid="bloomerp_refresh_automation_signals_delete",
	)

	_WORKFLOW_NODE_SIGNALS_CONNECTED = True


def setup_automation_signals(refresh: bool = False) -> None:
	"""Register create/update/delete signals for object-based workflow triggers."""
	global _SIGNALS_INITIALIZED
	_connect_workflow_node_signals()

	if _SIGNALS_INITIALIZED and not refresh:
		return

	if _SIGNALS_INITIALIZED and refresh:
		_disconnect_registered_handlers()

	create_triggers = WorkflowNode.get_triggers_by_type("ON_OBJECT_CREATE")
	update_triggers = WorkflowNode.get_triggers_by_type("ON_OBJECT_UPDATE")
	delete_triggers = WorkflowNode.get_triggers_by_type("ON_OBJECT_DELETE")

	trigger_sets = {
		"create": create_triggers,
		"update": update_triggers,
		"delete": delete_triggers,
	}

	for event, triggers in trigger_sets.items():
		grouped = _group_triggers_by_content_type(triggers)
		for content_type_id, content_triggers in grouped.items():
			content_type = ContentType.objects.filter(id=content_type_id).first()
			if not content_type:
				continue
			model_cls = content_type.model_class()
			if model_cls is None:
				continue

			handler = _create_handler(event, content_triggers)
			dispatch_uid = f"bloomerp_automation_{event}_{content_type_id}"
			if event in ("create", "update"):
				post_save.connect(handler, sender=model_cls, dispatch_uid=dispatch_uid)
			else:
				post_delete.connect(handler, sender=model_cls, dispatch_uid=dispatch_uid)

			_REGISTERED_HANDLERS[(event, content_type_id)] = (handler, model_cls)

	_SIGNALS_INITIALIZED = True