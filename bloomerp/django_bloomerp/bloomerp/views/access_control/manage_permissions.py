from bloomerp.models.application_field import ApplicationField
from bloomerp.field_types import FieldType
from registries.route_registry import router
from django.views.generic import TemplateView
from bloomerp.views.mixins import HtmxMixin
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.contrib.auth.models import Permission

@router.register(
    path='access-control',
    route_type='app',
)
class ManageAccessControlView(HtmxMixin, TemplateView):
    template_name = "access_control_views/manage_permissions.html"
    

@router.register(
    path='access-control',
    route_type='list',
    models='__all__',
)
class ManageAccessControlForModelView(HtmxMixin, TemplateView):
    template_name = "access_control_views/manage_permissions.html"
    model : Model = None
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        context["application_fields"] = ApplicationField.get_for_model(self.model).exclude(
            field_type__in=[FieldType.ONE_TO_MANY_FIELD.id, FieldType.PROPERTY.id]
        )
        context["content_type_id"] = ContentType.objects.get_for_model(self.model).id
        
        context["permissions"] = Permission.objects.filter(content_type__id=ContentType.objects.get_for_model(self.model).id)        
        return context
    
