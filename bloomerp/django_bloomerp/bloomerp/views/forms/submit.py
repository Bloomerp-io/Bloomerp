from django.contrib.contenttypes.models import ContentType
from django.contrib import messages
from django.views.generic.detail import DetailView

from bloomerp.models import ApplicationField
from bloomerp.models.forms.form import Form
from bloomerp.router import router
from bloomerp.services.form_services import FormManager
from bloomerp.views.mixins.layout_form_mixin import BloomerpLayoutFormMixin


@router.register(
    path="submit",
    route_type="detail",
    name="Submit",
    description="Submit a form",
    url_name="submit",
    models=[Form],
)
class SubmitFormView(
    BloomerpLayoutFormMixin,
    DetailView,
):
    template_name = "form_views/submit.html"
    model = Form
    module = None
    layout_mode = "form-submit"

    def has_permission(self):
        return True

    def get_layout_content_type(self) -> ContentType:
        return self.object.content_type

    def get_layout_object(self):
        return self.object.layout_obj

    def get_layout_object_content_type(self) -> ContentType:
        return ContentType.objects.get_for_model(Form)

    def get_layout_object_id(self):
        return self.object.pk

    def get_layout_preference_object(self):
        return None

    def get_layout_bound_object(self):
        return None

    def can_view_application_field(self, application_field: ApplicationField) -> bool:
        return application_field.content_type_id == self.get_layout_content_type().id

    def can_edit_application_field(self, application_field: ApplicationField) -> bool:
        return self.can_view_application_field(application_field)

    def can_render_unbound_editable_layout_field(self, application_field: ApplicationField) -> bool:
        return self.can_view_application_field(application_field)

    def get_layout_editable_field_names(self) -> list[str]:
        return FormManager(self.object).layout_field_names()

    def get_unbound_layout_field_value(self, application_field: ApplicationField):
        field_type_id = application_field.get_field_type_enum().value.id
        if field_type_id == "OneToManyField":
            return FormManager(self.object).get_one_to_many_initial_value(application_field.field)
        return super().get_unbound_layout_field_value(application_field)

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

    def can_change_layout(self) -> bool:
        return False

    def can_delete_layout_object(self) -> bool:
        return False

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = self.build_layout_form()
        manager = FormManager(self.object)

        if form is not None and form.is_valid():
            submission_resp = manager.register_submission(form.cleaned_data, request)
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
                    form_submission_message="Form successfully filled in.",
                )
            )

        messages.error(request, "An error occurred")

        return self.render_to_response(self.get_context_data(_layout_form=form))

    def get_context_data(self, **kwargs):
        self.object = self.get_object()
        context = super().get_context_data(**kwargs)
        context["form_object"] = self.object
        context["target_content_type"] = self.get_layout_content_type()
        context.setdefault("form_submission_error_message", None)
        if not context.get("form_submitted_successfully") and not FormManager(self.object).can_submit(self.request):
            context["form_submission_error_message"] = FormManager.MAX_SUBMISSIONS_MESSAGE
        return context
    
