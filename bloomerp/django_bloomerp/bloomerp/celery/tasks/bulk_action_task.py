from typing import Any

from celery import shared_task
from django.contrib.auth import get_user_model


@shared_task
def process_bulk_action(
    *,
    content_type_id: int,
    user_id: int,
    application_field_id: int,
    object_ids: list[str],
    value: Any,
) -> int:
    from bloomerp.models import ApplicationField
    from bloomerp.services.bulk_action_services import BulkActionService

    user = get_user_model().objects.get(pk=user_id)
    application_field = ApplicationField.objects.get(pk=application_field_id)
    service = BulkActionService.from_content_type_id(content_type_id=content_type_id, user=user)
    return service.update_field(
        application_field=application_field,
        object_ids=object_ids,
        value=value,
    )
