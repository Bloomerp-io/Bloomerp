from prompt_toolkit import Application
from bloomerp.router import router
from django.views.generic import TemplateView
from bloomerp.views.mixins import HtmxMixin
from django.db.models import Model
from django.contrib.contenttypes.models import ContentType
from bloomerp.models.access_control.policy import Policy
from bloomerp.models import ApplicationField

@router.register(
    path='access-control/policies/',
    route_type='list',
    models='__all__',
)
class ManageAccessControlForModelView(HtmxMixin, TemplateView):
    template_name = "access_control_views/policy_list.html"
    model : Model = None
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["fields"] = ApplicationField.get_for_model(Policy).filter(
            field__in=[
                "name",
                "description",
                "row_policy",
                "field_policy",
            ]
        )
        context["content_type_id"] = ContentType.objects.get_for_model(Policy).id
        context["queryset"] = Policy.get_policies_for_model(self.model)
        
        return context
    
