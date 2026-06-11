from celery import shared_task


from typing import Any


@shared_task
def process_bulk_upload_submission(
    *,
    content_type_id: int,
    user_id: int,
    file_id: str,
    changes: dict | None = None,
    rows: list[dict[str, Any]] | None = None,
    fields: list[str] | None = None,
):
    """Process a bulk upload draft inside a Celery worker.

    Args:
        content_type_id (int): Primary key of the content type being imported.
        user_id (int): Primary key of the user who initiated the import.
        file_id (str): Identifier of the stored draft file.
        changes (dict | None): Legacy sparse row and field edits collected during the
            wizard review step.
        rows (list[dict[str, Any]] | None): Effective row payloads prepared before the
            task was queued.
        fields (list[str] | None): Ordered field names included in each prepared row.

    Returns:
        int: Number of objects created from the draft.
    """
    from django.contrib.auth import get_user_model

    from bloomerp.services.bulk_services import BulkCrudService

    user = get_user_model().objects.get(pk=user_id)
    service = BulkCrudService.from_content_type_id(content_type_id=content_type_id, user=user)
    try:
        if rows is not None and fields is not None:
            return service._process_rows_impl(rows=rows, fields=fields)
        return service._process_draft_impl(file_id=file_id, changes=changes)
    finally:
        service.delete_draft_file(file_id)