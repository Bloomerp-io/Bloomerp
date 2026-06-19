"""Celery autodiscovery entrypoint for Bloomerp tasks.

Celery commonly autodiscovers ``<app>.tasks`` modules for each installed app.
The actual task implementations live in submodules, so importing them here ensures
their ``@shared_task`` declarations are registered when a worker or beat process
starts.
"""

from bloomerp.celery.tasks.bulk_upload_task import process_bulk_upload_submission
from bloomerp.celery.tasks.bulk_action_task import process_bulk_action
from bloomerp.celery.tasks.workflow_task import run_scheduled_workflow

__all__ = [
    "process_bulk_action",
    "process_bulk_upload_submission",
    "run_scheduled_workflow",
]
