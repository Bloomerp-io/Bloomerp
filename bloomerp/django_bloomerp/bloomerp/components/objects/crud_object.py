from django.contrib.contenttypes.models import ContentType
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse

from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.router import router
from bloomerp.utils.models import get_create_view_url
from bloomerp.utils.requests import render_blank_form
from bloomerp.views.core.create_view import BloomerpCreateView

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

    def form_valid(self, form):
        response = super().form_valid(form)
        if not self.request.htmx:
            return response

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
