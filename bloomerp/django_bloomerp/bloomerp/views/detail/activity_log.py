from typing import Any, Dict
from bloomerp.router import router
from bloomerp.views.core.base_detail import BloomerpBaseDetailView
from bloomerp.models.activity_log import ActivityLog

@router.register(
    path="/activity/",
    name="Activity",
    description="View activity for a specific object of the {model} model.",
    url_name="activity",
    route_type="detail",
    models="__all__",
)
class BloomerpDetailActivityView(BloomerpBaseDetailView):
    template_name = "detail_views/bloomerp_detail_activity_view.html"
    
    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        
        ActivityLog.objects.get_
        
        return context
    