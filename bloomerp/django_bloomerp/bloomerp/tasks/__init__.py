"""Task package exports for Celery autodiscovery.

Celery commonly autodiscovers ``<app>.tasks`` modules. This package imports task
modules that live alongside it so their ``@shared_task`` declarations execute
when the package is discovered by a worker.
"""

from .bulk_upload_task import process_bulk_upload_submission

__all__ = ["process_bulk_upload_submission"]
