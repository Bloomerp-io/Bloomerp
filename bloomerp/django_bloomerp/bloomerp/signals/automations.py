"""Setup signals for automations."""

import json
from collections import defaultdict
from typing import Iterable

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.utils import OperationalError, ProgrammingError
from django.db.models.signals import post_delete, post_save
from django_celery_beat.models import CrontabSchedule, PeriodicTask
from bloomerp.automation.defintion import WorkflowNodeType
from bloomerp.models.automation.workflow import Workflow
from bloomerp.models.automation.workflow_node import WorkflowNode
from bloomerp.services.workflow_services import run_workflow

_SIGNALS_INITIALIZED = False
_WORKFLOW_NODE_SIGNALS_CONNECTED = False
_SCHEDULE_SIGNALS_CONNECTED = False
_REGISTERED_HANDLERS: dict[tuple[str, int], tuple[object, object]] = {}
_SCHEDULE_TASK_NAME_PREFIX = "bloomerp.workflow.schedule."
_SCHEDULE_TASK = "bloomerp.celery.tasks.workflow_task.run_scheduled_workflow"


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


def _schedule_task_name(workflow_id: int) -> str:
	return f"{_SCHEDULE_TASK_NAME_PREFIX}{workflow_id}"


def _delete_schedule_task_for_workflow(workflow_id: int) -> None:
	PeriodicTask.objects.filter(name=_schedule_task_name(workflow_id)).delete()


def _parse_cronschedule(schedule: str) -> dict[str, str] | None:
	parts = str(schedule or "").split()
	if len(parts) != 5:
		return None

	minute, hour, day_of_month, month_of_year, day_of_week = parts
	return {
		"minute": minute,
		"hour": hour,
		"day_of_week": day_of_week,
		"day_of_month": day_of_month,
		"month_of_year": month_of_year,
	}


def _sync_schedule_task_for_workflow(workflow: Workflow) -> None:
	trigger = workflow.get_trigger()
	if not trigger or trigger.node_sub_type_id != "SCHEDULE":
		_delete_schedule_task_for_workflow(workflow.id)
		return

	params = (trigger.config or {}).get("parameters", {})
	cron_kwargs = _parse_cronschedule(params.get("schedule"))
	if cron_kwargs is None:
		_delete_schedule_task_for_workflow(workflow.id)
		return

	cron_kwargs["timezone"] = params.get("timezone") or settings.TIME_ZONE
	crontab, _ = CrontabSchedule.objects.get_or_create(**cron_kwargs)
	PeriodicTask.objects.update_or_create(
		name=_schedule_task_name(workflow.id),
		defaults={
			"task": _SCHEDULE_TASK,
			"crontab": crontab,
			"interval": None,
			"solar": None,
			"clocked": None,
			"args": json.dumps([workflow.id]),
			"enabled": workflow.active,
			"description": f"Scheduled Bloomerp workflow: {workflow.name}",
		},
	)


def _ignore_database_errors(func) -> None:
	try:
		func()
	except (OperationalError, ProgrammingError):
		pass


def _sync_schedule_task_for_workflow_safe(workflow: Workflow) -> None:
	try:
		transaction.on_commit(lambda: _ignore_database_errors(lambda: _sync_schedule_task_for_workflow(workflow)))
	except (OperationalError, ProgrammingError):
		pass


def _sync_schedule_task_after_workflow_save(sender, instance: Workflow, **kwargs) -> None:
	_sync_schedule_task_for_workflow_safe(instance)


def _delete_schedule_task_after_workflow_delete(sender, instance: Workflow, **kwargs) -> None:
	try:
		transaction.on_commit(lambda: _ignore_database_errors(lambda: _delete_schedule_task_for_workflow(instance.id)))
	except (OperationalError, ProgrammingError):
		pass


def _sync_schedule_task_after_node_save(sender, instance: WorkflowNode, **kwargs) -> None:
	if instance.type != WorkflowNodeType.TRIGGER.value.id:
		return

	_sync_schedule_task_for_workflow_safe(instance.workflow)


def _sync_schedule_task_after_node_delete(sender, instance: WorkflowNode, **kwargs) -> None:
	if instance.type != WorkflowNodeType.TRIGGER.value.id:
		return

	try:
		transaction.on_commit(lambda: _ignore_database_errors(lambda: _delete_schedule_task_for_workflow(instance.workflow_id)))
	except (OperationalError, ProgrammingError):
		pass


def _connect_schedule_signals() -> None:
	global _SCHEDULE_SIGNALS_CONNECTED
	if _SCHEDULE_SIGNALS_CONNECTED:
		return

	post_save.connect(
		_sync_schedule_task_after_workflow_save,
		sender=Workflow,
		dispatch_uid="bloomerp_sync_schedule_task_workflow_save",
	)
	post_delete.connect(
		_delete_schedule_task_after_workflow_delete,
		sender=Workflow,
		dispatch_uid="bloomerp_sync_schedule_task_workflow_delete",
	)
	post_save.connect(
		_sync_schedule_task_after_node_save,
		sender=WorkflowNode,
		dispatch_uid="bloomerp_sync_schedule_task_node_save",
	)
	post_delete.connect(
		_sync_schedule_task_after_node_delete,
		sender=WorkflowNode,
		dispatch_uid="bloomerp_sync_schedule_task_node_delete",
	)

	_SCHEDULE_SIGNALS_CONNECTED = True


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
	_connect_schedule_signals()

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
