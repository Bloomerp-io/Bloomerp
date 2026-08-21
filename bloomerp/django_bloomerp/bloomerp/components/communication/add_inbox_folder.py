from bloomerp.communication.inbox_folder_definition import InboxFolderType, InboxFolderTypeDefinition
from bloomerp.models.communication.inbox.inbox import Inbox
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.communication.utils.permissions import manageable_inboxes
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.mixins.wizard_mixin import WizardError, WizardMixin, WizardStep
from django.http import HttpResponse
from django.views.generic import TemplateView
from bloomerp.router import router
from django_htmx.http import HttpResponseClientRefresh

SESSION_KEY = "add_inbox_folder_wizard"

@router.register(
    path="components/communication/add_inbox_folder/<str:inbox_id>/",
    url_name="components_add_inbox_folder",
)
class AddInboxFolder(WizardMixin, BaseBloomerpView, TemplateView):
    inbox_id: str
    
    def dispatch(self, request, *args, **kwargs):
        self.inbox_id = kwargs.get("inbox_id")
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not manageable_inboxes(request.user).filter(pk=self.inbox_id).exists():
            return HttpResponse(
                "Only the inbox owner can add folders.",
                status=403,
            )
        return super().dispatch(request, *args, **kwargs)
    
    def get_folder_type(self) -> InboxFolderTypeDefinition:
        folder_type_key = self.orchestrator.get_session_data("folder_type")
        if not folder_type_key:
            raise ValueError("Folder type not set in session data")
        
        folder_type : InboxFolderType = InboxFolderType.from_key(folder_type_key)
        if not folder_type:
            raise ValueError(f"Invalid folder type key: {folder_type_key}")
        
        return folder_type.value
    
    def get_step(self, step):
        if step == 0:
            return WizardStep(
                name="Select Folder Type",
                description="Select the type of inbox folder you want to create.",
                template_name="cotton/ui/inputs/selectable_cards/container.html",
                context_func=lambda _,__,___: {
                    "items" : [
                        {
                            "icon": i.value.icon,
                            "name": i.value.name,
                            "description": i.value.description,
                            "value": i.value.key,
                        }
                        for i in InboxFolderType
                    ],
                    "name" : "folder_type",
                },
                process_func=lambda request,self,orchestrator:(
                    orchestrator.set_session_data("folder_type", request.POST.get("folder_type"))
                )
            )
        
        if step == 1:    
            try:
                folder_type = self.get_folder_type()
            except ValueError as e:
                return WizardError(str(e))
            
            source_model = folder_type.get_source_model_class()
            if not source_model:
                return
            
            # Get the items the user has access to
            # Note: change permission because the user will 
            manager = UserPolicyManager(self.request.user)
            objects = manager.get_queryset(
                source_model,
                BloomerpPermission.CHANGE
            )
            
            return WizardStep(
                name=f"Select {source_model._meta.verbose_name} for {folder_type.name} Folder",
                description=f"Select a {source_model._meta.verbose_name} for the {folder_type.name} inbox folder.",
                template_name="cotton/ui/inputs/selectable_cards/container.html",
                context_func=lambda _, __, ___: {
                    "items" : [
                        {
                            "icon": folder_type.icon,
                            "name": str(i),
                            "description": "",
                            "value": i.pk,
                        }
                        for i in objects
                    ],
                    "name" : "related_object_id",
                },
                process_func=lambda request,_,orchestrator: (
                    orchestrator.set_session_data("related_object_id", request.POST.get("related_object_id"))
                )
            )
    
    def get_inbox(self) -> Inbox:
        try:
            return manageable_inboxes(self.request.user).get(pk=self.inbox_id)
        except Inbox.DoesNotExist:
            raise ValueError(
                f"Inbox with id {self.inbox_id} does not exist or cannot be managed"
            )
        
    def done(self):
        # Get the data
        folder_type = self.get_folder_type()
        inbox = self.get_inbox()
        related_object_id = self.orchestrator.get_session_data("related_object_id")
        
        # Create the inbox folder
        InboxFolder.objects.create(
            inbox=inbox,
            type=folder_type.key,
            related_object_id=related_object_id if related_object_id else None
        )
        
        return HttpResponseClientRefresh()
