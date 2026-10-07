from bloomerp.communication.builtins.in_app_notifications.base import BaseSystemMessageType, SystemMessageItemData
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.db.models import Q
from bloomerp.communication.inbox_sources import (
    InboxSourceDelivery,
    InboxSourceExecutionResult,
)

# TODO: Handling for deleted form submissions
class FormSubmissionMessage(BaseSystemMessageType):
    @classmethod
    def build_item_data(cls, data: dict) -> SystemMessageItemData:
        return SystemMessageItemData(
            title=f"New submission for {data.get('form_name') or ''}",
            snippet="A new form submission is ready for review.",
            raw_meta_data=data,
        )

    @classmethod
    def render(cls, item, request: HttpRequest | None = None) -> str:
        from bloomerp.models.forms.form_submission import FormSubmission
        try:
            submission = FormSubmission.objects.get(
                pk=item.raw_meta_data.get("submission_id")
            )
        except:
            pass
        
        return render_to_string(
            "inbox_items/form_submission.html",
            {
                "submission": submission,
                
            },
            request=request,
        )
        
        
def should_notify_form_submission(
    *,
    instance,
    created: bool,
    raw: bool = False,
    **kwargs,
) -> bool:
    return created and not raw and instance.form_id is not None


def resolve_form_submission_folders(*, instance, **kwargs):
    """Resolve the folders

    Args:
        instance (_type_): _description_

    Returns:
        _type_: _description_
    """
    from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder

    recipient_id = instance.form.created_by_id
    if recipient_id is None:
        return InboxFolder.objects.none()

    folders = InboxFolder.get_folders_by_users_and_type(
        users=recipient_id,
        folder_type=INBOX_FOLDER_REGISTRY.IN_APP_NOTIFICATIONS.key
    )
    return folders
    

def handle_form_submission(folders, *, instance, **kwargs):
    """Handles a form submission message

    Args:
        folders (folders): The folders
        instance (FormSubmission): the form submission

    Returns:
        _type_: _description_
    """
    from bloomerp.communication.builtins.in_app_notifications.base import SystemMessage

    deliveries = []

    for folder in folders:
        item = SystemMessage.create_item(
            message_type="form_submission",
            folder=folder,
            data={
                "submission_id": str(instance.pk),
                "form_id": str(instance.form_id),
                "title": f"New submission for {instance.form.name}",
                "message": "A new form submission is ready for review.",
                "form_name": instance.form.name,
                "submitted_at": instance.datetime_created.isoformat(),
            },
        )
        deliveries.append(
            InboxSourceDelivery(
                folder=folder,
                items=(item,),
            )
        )

    return InboxSourceExecutionResult(
        deliveries=tuple(deliveries),
        metrics={
            "submission_id": str(instance.pk),
            "recipient_folders": len(deliveries),
        },
    )
