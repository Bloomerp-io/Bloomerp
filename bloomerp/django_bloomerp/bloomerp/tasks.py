"""Celery autodiscovery entrypoint for Bloomerp tasks.

Celery commonly autodiscovers ``<app>.tasks`` modules for each installed app.
The actual task implementations live in submodules, so importing them here ensures
their ``@shared_task`` declarations are registered when a worker or beat process
starts.
"""

from bloomerp.celery.tasks.agent_task import execute_agent_run
from bloomerp.celery.tasks.bulk_upload_task import process_bulk_upload_submission
from bloomerp.celery.tasks.inbox_source_task import execute_inbox_source_task
from bloomerp.celery.tasks.workflow_task import run_scheduled_workflow
from bloomerp.utils.async_utils import run_serialized_async_job

__all__ = [
    "execute_agent_run",
    "execute_inbox_source_task",
    "process_bulk_upload_submission",
    "run_scheduled_workflow",
    "run_serialized_async_job",
]
