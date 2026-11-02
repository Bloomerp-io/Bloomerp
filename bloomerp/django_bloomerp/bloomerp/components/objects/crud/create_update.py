import json
from copy import copy
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.contrib.messages import get_messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import resolve, reverse
from django_htmx.http import HttpResponseClientRedirect

from bloomerp.forms.model_form import BloomerpModelForm, bloomerp_modelform_factory
from bloomerp.models.definition import apply_model_base_filter
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.utils.models import get_create_view_url, get_detail_view_url
from bloomerp.utils.requests import render_blank_form
from bloomerp.views.generic.model.create import BloomerpCreateView


def _get_detail_url(obj) -> str:
    try:
        return obj.get_absolute_url()
    except Exception:
        try:
            return reverse(get_detail_view_url(obj.__class__), kwargs={"pk": obj.pk})
        except Exception:
            return ""


@router.register(
    path="components/create-object/<int:content_type_id>/",
    name="components_create_object",
)
class CreateObjectComponentView(BloomerpCreateView):
    htmx_include_addendum = False

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Render creation in its caller's modal, using custom views' canonical paths and initial values."""
        self.content_type = get_object_or_404(ContentType, id=kwargs["content_type_id"])
        self.model = self.content_type.model_class()
        if self.model is None:
            return HttpResponse("Invalid content type", status=400)
        if self._create_view_is_overridden() and not getattr(request, "_bloomerp_custom_create", False):
            url = reverse(get_create_view_url(self.model))
            if request.GET.get("data_view_create_id") or request.POST.get("data_view_create_id"):
                if not UserPolicyManager(request.user).has_global_permission(self.model, "add"):
                    return HttpResponse("Forbidden", status=403)
                match = resolve(url)
                callback = match.func
                view_class = getattr(callback, "view_class", None)
                if view_class is not None and hasattr(view_class, "htmx_include_addendum"):
                    callback = view_class.as_view(**{
                        **callback.view_initkwargs, "htmx_include_addendum": False,
                    })
                custom_request = copy(request)
                custom_request.path = url
                custom_request.path_info = url
                custom_request.resolver_match = match
                custom_request._bloomerp_custom_create = True
                return callback(custom_request, *match.args, **match.kwargs)
            query = request.GET.urlencode()
            return HttpResponseClientRedirect(f"{url}?{query}" if query else url)
        return super().dispatch(request, *args, **kwargs)

    def _create_view_is_overridden(self) -> bool:
        create_url_name = get_create_view_url(self.model)
        return any(
            route.url_name == create_url_name and route.override
            for route in router.get_routes_by_model(self.model)
        )

    def get_form_hx_target(self) -> str:
        """Keep form submissions and validation errors inside their own dialog."""
        return "closest [data-modal-body]"

    def get_form_hx_push_url(self) -> bool:
        return False

    def get_non_required_fields_visible_default(self) -> bool:
        return False

    def get_full_form_url(self) -> str | None:
        return reverse(get_create_view_url(self.model))

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Preserve the originating widget or data view across validation responses."""
        context = super().get_context_data(**kwargs)
        context["foreign_field_widget_id"] = (
            self.request.POST.get("foreign_field_widget_id")
            or self.request.GET.get("foreign_field_widget_id")
            or ""
        )
        context["data_view_create_id"] = (
            self.request.POST.get("data_view_create_id")
            or self.request.GET.get("data_view_create_id")
            or ""
        )
        return context

    def form_valid(self, form: BloomerpModelForm) -> HttpResponse:
        """Save the object and notify the caller while preserving other create flows."""
        response = super().form_valid(form)
        if not self.request.htmx or form.errors:
            return response

        # This code is here to ensure that the foreign key widget
        # will be able to create and set the value of the actual
        # widget
        # TODO: We probably wanna come up with a better pattern for this in the future 
        foreign_field_widget_id = self.request.POST.get("foreign_field_widget_id") or self.request.GET.get("foreign_field_widget_id")
        if foreign_field_widget_id:
            htmx_response = HttpResponse(status=204)
            htmx_response["HX-Trigger"] = json.dumps(
                {
                    "bloomerp:foreign-field-object-created": {
                        "foreign_field_widget_id": foreign_field_widget_id,
                        "content_type_id": self.content_type.pk,
                        "object_id": str(self.object.pk),
                        "object_label": str(self.object),
                        "object_detail_url": _get_detail_url(self.object),
                    }
                }
            )
            return htmx_response

        if self.request.POST.get("next"):
            return redirect(self.request.POST.get("next"))

        htmx_response = HttpResponse(status=204)
        data_view_create_id = self.request.POST.get("data_view_create_id")
        if data_view_create_id:
            htmx_response["HX-Trigger"] = json.dumps({
                "bloomerp:data-view-object-created": {
                    "data_view_create_id": data_view_create_id,
                    "messages": [
                        {"text": str(message), "type": message.level_tag}
                        for message in get_messages(self.request)
                    ],
                },
            })
            return htmx_response
        htmx_response["HX-Refresh"] = "true"
        return htmx_response


@router.register(
    path="components/update-object/<int:content_type_id>/<str:object_id>/",
    name="components_update_object",
)
def update_object(request:HttpRequest, content_type_id:int, object_id:str|int) -> HttpResponse:
    """Resolve the update component within the model's configured base filter.

    Args:
        request (HttpRequest): the request object
        content_type_id (int): the content type ID
        object_id (str|int): the object ID

    Returns:
        HttpResponse: the response object
    """
    # TODO : Integrate permissions using permissions services
    content_type = ContentType.objects.get(id=content_type_id)
    ModelCls = content_type.model_class()
    object = get_object_or_404(
        apply_model_base_filter(ModelCls._default_manager.all()), id=object_id
    )
    FormCls = bloomerp_modelform_factory(ModelCls, "__all__")
    
    if request.method == "GET":    
    
        return render_blank_form(
            request,
            FormCls(instance=object),
            {},
            ""
        )
    elif request.method == "POST":
        form = FormCls(instance=object, data=request.POST, files=request.FILES)
