import json
from typing import Any
from django.urls import reverse
from bloomerp.communication.definition import InboxFolderTypeFilterDefinition
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.views.communication.create_email_account import EmailAccountSettingsForm

from bloomerp.communication.definition import INBOX_ITEM_RENDER_TARGET, INBOX_ITEMS_TARGET, INBOX_MESSAGE_TARGET
from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.user_inbox_preference import UserInboxPreference
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.views.base import BaseBloomerpView
from bloomerp.router import router
from django.views.generic import TemplateView

@router.register(
    path="/inbox",
    route_type="app",
    url_name="inbox",
    name="Inbox",
)
class InboxView(BaseBloomerpView, TemplateView):
    htmx_include_addendum_padding = False
    template_name = "views/communication/inbox.html"
    
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Present accessible inbox folders and their configured mailbox labels."""
        ctx = super().get_context_data(**kwargs)
        preference_manager = PreferenceManager(self.request.user)
        inbox = preference_manager.get_or_create_selected(
            Inbox,
            force_create=False,
        )
        inbox_preference = self.get_inbox_preference(inbox)
        ctx["inbox_types"] = [
            folder_type
            for folder_type in INBOX_FOLDER_REGISTRY.values()
            if not folder_type.source_model
        ]
        ctx["inbox"] = inbox
        ctx["inbox_preference"] = inbox_preference
        ctx["can_manage_inbox"] = bool(
            inbox and preference_manager.can_manage(inbox)
        )
        
        if inbox and inbox_preference and inbox_preference.selected_inbox_folder:
            folders = inbox.folders.all()
            selected_folder = inbox_preference.selected_inbox_folder
            folder_type = selected_folder.inbox_folder_type()
            filters = folder_type.resolve_filters(selected_folder)
            ctx["folder_options"] = [
                {
                    "folder": folder,
                    "subfolders": self.get_subfolder_filter_options(folder),
                }
                for folder in folders
            ]
            ctx["filters"] = [
                self._serialize_filter_option(filter_definition)
                for filter_definition in filters
                if not filter_definition.is_subfolder
            ]
            actions = folder_type.actions or []
            ctx["actions"] = actions
            ctx["primary_actions"] = [action for action in actions if action.is_primary_action]
            ctx["secondary_actions"] = [action for action in actions if not action.is_primary_action]
        
        # Add targets
        ctx["targets"] = {
            "inbox_items" : INBOX_ITEMS_TARGET,
            "item_render" : INBOX_ITEM_RENDER_TARGET,
            "message" : INBOX_MESSAGE_TARGET,
        }
        
        return ctx


    def get_subfolder_filter_options(self, folder: InboxFolder) -> list[dict[str, object]]:
        """Serialize mailbox choices for this folder."""
        return [
            self._serialize_filter_option(filter_definition)
            for filter_definition in folder.inbox_folder_type().resolve_filters(folder)
            if filter_definition.is_subfolder
        ]

    def _serialize_filter_option(
        self, filter_definition: InboxFolderTypeFilterDefinition,
    ) -> dict[str, object]:
        """Encode shared predicates and query controls for the inbox preset data attribute."""
        query_params = dict(filter_definition.query_params)
        if filter_definition.filters:
            query_params["filter"] = json.dumps([
                group.model_dump() for group in filter_definition.filters
            ])
        return {
            "key": filter_definition.key,
            "name": filter_definition.name,
            "color": filter_definition.color,
            "filters_json": json.dumps(query_params, separators=(",", ":")),
        }

    def get_inbox_preference(
        self,
        inbox: Inbox | None,
    ) -> UserInboxPreference | None:
        if inbox is None:
            return None

        preference = UserInboxPreference.get_for_user(self.request.user)
        selected_folder = (
            inbox.folders.filter(pk=preference.selected_inbox_folder_id).first()
            if preference.selected_inbox_folder_id
            else None
        )
        if selected_folder is None:
            selected_folder = inbox.folders.order_by("pk").first()
            preference.selected_inbox_folder = selected_folder
            preference.save(update_fields=["selected_inbox_folder"])
        return preference
    
    
