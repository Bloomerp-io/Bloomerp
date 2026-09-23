from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic.detail import DetailView

from bloomerp.forms.model_form import BloomerpModelForm
from bloomerp.models.forms.form import Form
from bloomerp.router import router
from bloomerp.services.form_services import FormManager
from bloomerp.views.mixins.application_field_layout_form_mixin import (
    ApplicationFieldLayoutFormMixin,
)
from bloomerp.views.mixins.layout_mixin import LayoutBinding
from django_htmx.http import HttpResponseClientRedirect


@router.register(
    path="submit",
    route_type="detail",
    name="Submit",
    description="Submit a form",
    url_name="submit",
    models=[Form],
)
class SubmitFormView(ApplicationFieldLayoutFormMixin, DetailView):
    apply_permissions = False
    template_name = "views/forms/submit.html"
    model = Form
    module = None
    layout_mode = "create"
    
    def get(self, request, *args, **kwargs):
        if request.htmx:
            return HttpResponseClientRedirect(
                reverse("forms_detail_submit", kwargs={"pk": self.get_object().pk})
            )

        return super().get(request, *args, **kwargs)

    def has_permission(self):
        return True

    def get_layout_binding(self) -> LayoutBinding:
        form = getattr(self, "object", None) or self.get_object()
        self.object = form
        return LayoutBinding(
            owner=form,
            target_content_type=form.content_type,
            layout_mode=self.layout_mode,
        )

    def get_view_permission_str(self) -> str:
        return ""

    def get_change_permission_str(self) -> str:
        return ""

    def build_layout_form(self):
        manager = FormManager(self.object)
        form_class = manager.layout_form_cls()
        if form_class is None:
            return None
        
        kwargs = {"initial": manager.get_initial_form_data()}
        if self.request.method.upper() == "POST":
            kwargs["data"] = self.request.POST
            kwargs["files"] = self.request.FILES
        return form_class(**kwargs)

    def get_form(self):
        cached_form = getattr(self, "_layout_form", None)
        if cached_form is None:
            cached_form = self.build_layout_form()
            self._layout_form = cached_form
        
        self.apply_layout_widget_config(
            form=cached_form
        )
        return cached_form
    
    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        """Register a valid submission and render its configured success message."""
        self.object = self.get_object()
        form = self.get_form()
        manager = FormManager(self.object)
        
        if form is not None and form.is_valid():
            submission_resp = manager.register_submission(form, request)
            if not submission_resp.submitted:
                return self.render_to_response(
                    self.get_context_data(
                        _layout_form=form,
                        form_submission_error_message=submission_resp.message,
                    )
                )
            
            return self.render_to_response(
                self.get_context_data(
                    form_submitted_successfully=True,
                    form_submission_message=(
                        self.object.success_text or _("Form successfully filled in.")
                    ),
                )
            )

        messages.error(request, "An error occurred")

        return self.render_to_response(self.get_context_data(_layout_form=form))

    def get_context_data(self, **kwargs):
        explicit_form = kwargs.pop("_layout_form", None)
        if explicit_form is not None:
            self._layout_form = explicit_form
        self.object = self.get_object()
        context = super().get_context_data(**kwargs)
        context["form_object"] = self.object
        context["target_content_type"] = self.layout_content_type
        context.setdefault("form_submission_error_message", None)
        if not context.get("form_submitted_successfully") and not FormManager(self.object).can_submit(self.request):
            context["form_submission_error_message"] = FormManager.MAX_SUBMISSIONS_MESSAGE
        return context
    
