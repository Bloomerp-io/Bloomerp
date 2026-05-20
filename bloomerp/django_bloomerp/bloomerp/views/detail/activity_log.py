from typing import Any, Dict
from bloomerp.router import router
from bloomerp.services.activity_log_services import ActivityLogManager
from bloomerp.views.detail.base_detail import BaseBloomerpDetailView
from django.apps import apps

@router.register(
    path="/activity/",
    name="Activity",
    description="View activity for a specific object of the {model} model.",
    url_name="activity",
    route_type="detail",
    models=[model for model in apps.get_models() if ActivityLogManager.should_record_change(model)],
)
class BloomerpDetailActivityView(BaseBloomerpDetailView):
    template_name = "detail_views/bloomerp_detail_activity_view.html"
    
    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        manager = ActivityLogManager(self.get_object())
        
        context["queryset"] = manager.get_for_object()
        return context
    