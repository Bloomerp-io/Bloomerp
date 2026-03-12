from django.db import models
from django.conf import settings
from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.mixins import AbsoluteUrlModelMixin

class Workspace(AbsoluteUrlModelMixin, models.Model):
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_workspace'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE
        )
    sub_module_id = models.CharField(max_length=255, default="")
    module_id = models.CharField(max_length=255, default="")
    layout = models.JSONField(default=dict)

    @classmethod
    def get_or_create_for_user(cls, user, module_id: str = "", sub_module_id: str = ""):
        from bloomerp.services.sectioned_layout_services import get_default_workspace_layout, layout_has_items

        workspace = cls.objects.filter(
            user=user,
            module_id=module_id,
            sub_module_id=sub_module_id,
        ).first()
        if workspace:
            if not layout_has_items(workspace.layout):
                workspace.layout = get_default_workspace_layout().model_dump()
                workspace.save(update_fields=["layout"])
            return workspace
        return cls.objects.create(
            user=user,
            module_id=module_id,
            sub_module_id=sub_module_id,
            layout=get_default_workspace_layout().model_dump(),
        )

    @property
    def layout_obj(self):
        from bloomerp.services.sectioned_layout_services import normalize_layout_payload
        return normalize_layout_payload(self.layout)
    
    
    
