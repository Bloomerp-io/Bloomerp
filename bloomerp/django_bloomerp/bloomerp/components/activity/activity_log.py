from typing import Any, Dict

from django.http import HttpRequest, HttpResponse
from bloomerp.router import router
from bloomerp.services.activity_log_services import ActivityLogManager
from bloomerp.views.detail.base_detail import BaseBloomerpDetailView
from django.apps import apps
from django.shortcuts import render

@router.register(
    path="components/activity-log/",
    url_name="components_activity_log",
)
def activity_log(request:HttpRequest) -> HttpResponse:
    object_id = request.GET.get("object_id")
    content_type_id = request.GET.get("content_type_id")
    context: dict[str, Any] = {}
    
    # Get content type and model class
    try:
        content_type_id_int = int(content_type_id) if content_type_id else None
    except ValueError:
        return HttpResponse("Invalid content_type_id", status=400)
    
    content_type = apps.get_model("contenttypes.ContentType").objects.filter(id=content_type_id_int).first() if content_type_id_int else None
    model_class = content_type.model_class() if content_type else None
    object_instance = model_class.objects.filter(id=object_id).first() if model_class and object_id else None
    
    if not ActivityLogManager.should_record_change(model_class):
        return HttpResponse("Activity logging is not enabled for this model.", status=400)
    
    
    if not object_id or not content_type_id:
        return HttpResponse("Missing object_id or content_type_id", status=400)
    
    manager = ActivityLogManager(object_instance)
    
    return render(
        request,
        "detail_views/bloomerp_detail_activity_view.html",
        context={
            "object_id": object_id,
            "content_type_id": content_type_id,
            "queryset": manager.get_for_object(),
        }
    )
    