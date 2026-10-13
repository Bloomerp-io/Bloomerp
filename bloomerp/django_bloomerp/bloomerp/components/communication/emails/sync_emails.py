import datetime

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.http import HttpResponse
from typing import TYPE_CHECKING
from bloomerp.celery.utils import is_celery_available
from bloomerp.communication.builtins.emails.actions import refresh_mailboxes_for_account
from bloomerp.communication.inbox_sources import publish_event
from bloomerp.communication.utils.permissions import accessible_inbox_folders
from bloomerp.router import router
from bloomerp.utils.requests import render_blank_form, render_message
from django import forms
from django.urls import reverse

if TYPE_CHECKING:
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder


class SyncEmailsForm(forms.Form):
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Start Date",
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="End Date",
        initial=datetime.date.today()
    )
    limit = forms.IntegerField(
        required=False,
        min_value=1,
        label="Limit",
        help_text="Maximum number of emails to sync per mailbox.",
        initial=100
    )
    mailboxes = forms.MultipleChoiceField(
        required=False,
        choices=[],
        label="Mailboxes",
        help_text="Select specific mailboxes to sync. Leave blank to sync all mailboxes.",
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, mailboxes: list[str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        mailbox_values = list(mailboxes or [])
        mailbox_choices = [(mailbox, mailbox) for mailbox in mailbox_values]
        self.fields["mailboxes"].choices = mailbox_choices
        self.fields["mailboxes"].initial = mailbox_values
    


@router.register(
    path="components/communication/sync_emails/<str:folder>",
    url_name="components_sync_emails"
)
@login_required
def sync_emails(request: HttpRequest, folder: "str | InboxFolder") -> HttpResponse:
    from bloomerp.models.communication.inbox.inbox_folder import InboxFolder

    folder_id = folder.pk if isinstance(folder, InboxFolder) else folder
    folder = accessible_inbox_folders(request.user).filter(pk=folder_id).first()
    if folder is None:
        return HttpResponse("Inbox folder not found.", status=404)
    email_account = folder.related_object()
    if not email_account:
        return render_message(
            request=request,
            message="This inbox folder is not connected to an email account.",
            type="danger",
        )

    available_mailboxes = email_account.mailboxes

    if request.method == "GET":
        try:
            available_mailboxes = refresh_mailboxes_for_account(email_account)
        except ValidationError as exc:
            return render_message(
                request=request,
                message=" ".join(exc.messages),
                type="danger",
            )
    
    text = "Synchronize your emails starting from the specified date range. Please select the start and end dates for synchronization."
    if not is_celery_available():
        text += "</br></br>Note: Celery is not available in the current environment. Email synchronization may not work as expected." 
    
    btn_text = "Sync Emails"
    btn_args = {
        "bloomerp-close-modal" : "bloomerp-general-use-modal",
    }
    
    if request.method == "GET":
        return render_blank_form(
            request=request,
            form=SyncEmailsForm(mailboxes=available_mailboxes),
            url=reverse(
                "components_sync_emails",
                args=[folder.id],
            ),
            text=text,
            submit_label=btn_text,
            button_attrs=btn_args
        )
    if request.method == "POST":
        form = SyncEmailsForm(request.POST, mailboxes=available_mailboxes)
        if form.is_valid():
            start_date = form.cleaned_data.get("start_date")
            end_date = form.cleaned_data.get("end_date")
            limit = form.cleaned_data.get("limit") or 50
            mailboxes = form.cleaned_data.get("mailboxes")
            
            try:
                receipt = publish_event(
                    key="email.sync.account",
                    email_account_id=email_account.id,
                    from_date=start_date,
                    to_date=end_date,
                    limit=limit,
                    mailboxes=mailboxes,
                )
            except ValidationError as exc:
                return render_message(
                    request=request,
                    message=" ".join(exc.messages),
                    type="danger",
                )

            if receipt.state == "scheduled":
                return render_message(
                    request=request,
                    message="Email synchronization has been initiated asynchronously. You will be notified once the process is complete.",
                    type="info"
                )

            synced_count = receipt.result.item_count if receipt.result else 0
            return HttpResponse(
                f"Synced {synced_count} emails from {start_date} to {end_date}"
            )
        else:
            return render_blank_form(
                request=request,
                form=form,
                url=reverse(
                    "components_sync_emails",
                    args=[folder.id],
                ),
                text=text,
                submit_label=btn_text,
                button_attrs=btn_args
            )
            
    
    
