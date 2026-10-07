from django.utils.translation import gettext_lazy as _
from typing import Type

from django.db import models
from django.db.models import Q
from bloomerp.communication.definition import InboxFolderTypeDefinition
from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY, inbox_folder_choices
from bloomerp.models import BloomerpModel
from bloomerp.models.communication.inbox.inbox_item import InboxItem
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.utils.requests import parse_bool_parameter
from django.db.models.query import QuerySet

class InboxFolder(BloomerpModel):
    class Meta:
        verbose_name = _("Inbox Folder")
        verbose_name_plural = _("Inbox Folders")
        db_table = "bloomerp_inbox_folder"
    
    inbox = models.ForeignKey(
        "Inbox",
        on_delete=models.CASCADE,
        related_name="folders",
        verbose_name=_("Inbox"),
    )
    type = models.CharField(
        max_length=50,
        choices=inbox_folder_choices,
        verbose_name=_("Type"),
    )
    related_object_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("Related Object ID"),
    )
    
    @property
    def name(self) -> str:
        """
        Returns a human-readable name for the folder based on its type.
        """
        if self.related_object():
            return str(self.related_object())
        return self.inbox_folder_type().name
    
    @property
    def icon(self) -> str:
        """
        Returns the icon associated with the folder's type.
        """
        return self.inbox_folder_type().icon
    
    def related_object(self) -> models.Model | None:
        """
        Returns the related object for the folder, if any.
        """
        source_model = self.related_model()
        if not source_model or not self.related_object_id:
            return None
        
        try:
            return source_model.objects.get(pk=self.related_object_id)
        except source_model.DoesNotExist:
            return None
    
    def related_model(self) -> Type[models.Model] | None:
        """
        Returns the model class associated with the folder's type.
        """
        return self.inbox_folder_type().get_source_model_class()
    
    def inbox_folder_type(self) -> InboxFolderTypeDefinition:
        """
        Returns the registered definition corresponding to the folder's type.
        """
        folder_type = INBOX_FOLDER_REGISTRY.get(self.type)
        if folder_type is None:
            raise ValueError(f"Unsupported inbox folder type: {self.type}")
        return folder_type
    
    def query_items(self, query_params: dict[str, str]) -> QuerySet[InboxItem]:
        """Dispatch predicate and provider controls to the selected folder query handler."""
        query_params = dict(query_params)
        deep_query = parse_bool_parameter(query_params.pop("deep_query", None))
        deep_search = parse_bool_parameter(query_params.pop("deep_search", None))
        return self.inbox_folder_type().on_query(query_params, self, deep_query or deep_search)

    def __str__(self) -> str:
        """
        Returns a string representation of the folder.
        """
        return f"{self.name} ({self.type})"

    def get_recipients(self) -> QuerySet[AbstractBloomerpUser]:
        from django.contrib.auth import get_user_model
        
        # Protect from initial default inboxes
        if self.inbox.initial_default:
            return get_user_model().objects.filter(
                id=self.inbox.user_id
            )
        
        return get_user_model().objects.filter(
            Q(pk=self.inbox.user_id)
            | Q(shared_inbox_preferences=self.inbox)
            | Q(groups__shared_inbox_preferences=self.inbox)
            
        ).distinct()

    
    @staticmethod
    def get_folders_by_users_and_type(
        users: list[AbstractBloomerpUser] | list[int] | int | AbstractBloomerpUser,
        folder_type: InboxFolderTypeDefinition | str,
    ) -> QuerySet["InboxFolder"]:
        """
        Returns a queryset of InboxFolder instances for the given users and folder type.
        """
        if isinstance(users, int):
            user_ids = [users]
        
        elif isinstance(users, AbstractBloomerpUser):
            user_ids = [users.pk]
            
        elif isinstance(users, list):
            user_ids = [
                user.pk if isinstance(user, AbstractBloomerpUser) else user
                for user in users
            ]
        else:
            raise ValueError("Invalid type for users parameter.")
        
        return InboxFolder.objects.filter(
            Q(inbox__user_id__in=user_ids)
            | Q(inbox__shared_with_users__id__in=user_ids)
            | Q(inbox__shared_with_groups__user__id__in=user_ids),
            inbox__source_object__isnull=True,
            type=(
                folder_type.key
                if isinstance(folder_type, InboxFolderTypeDefinition)
                else folder_type
            ),
        ).distinct()
