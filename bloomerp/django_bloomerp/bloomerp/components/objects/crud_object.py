import json

from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse

from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.router import router
from bloomerp.utils.models import get_create_view_url, get_detail_view_url
from bloomerp.utils.requests import render_blank_form
from bloomerp.views.core.create_view import BloomerpCreateView
from django_htmx.http import HttpResponseClientRedirect


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

    def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        self.content_type = get_object_or_404(ContentType, id=kwargs["content_type_id"])
        self.model = self.content_type.model_class()
        if self.model is None:
            return HttpResponse("Invalid content type", status=400)
        return super().dispatch(request, *args, **kwargs)

    def get_form_hx_target(self) -> str:
        return "#create-object-modal-body"

    def get_form_hx_push_url(self) -> bool:
        return False

    def get_non_required_fields_visible_default(self) -> bool:
        return False

    def get_full_form_url(self) -> str | None:
        return reverse(get_create_view_url(self.model))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["foreign_field_widget_id"] = (
            self.request.POST.get("foreign_field_widget_id")
            or self.request.GET.get("foreign_field_widget_id")
            or ""
        )
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        if not self.request.htmx:
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
                        "object_id": self.object.pk,
                        "object_label": str(self.object),
                        "object_detail_url": _get_detail_url(self.object),
                    }
                }
            )
            return htmx_response

        htmx_response = HttpResponse(status=204)
        htmx_response["HX-Refresh"] = "true"
        return htmx_response


@router.register(
    path="components/update-object/<int:content_type_id>/<str:object_id>/",
    name="components_update_object",
)
def update_object(request:HttpRequest, content_type_id:int, object_id:str|int) -> HttpResponse:
    """Returns the delete object component

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
    object = get_object_or_404(ModelCls, id=object_id)
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
