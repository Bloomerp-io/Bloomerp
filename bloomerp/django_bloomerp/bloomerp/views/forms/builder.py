from bloomerp.router import router
from django.contrib.contenttypes.models import ContentType
from django.views.generic.detail import DetailView

from bloomerp.forms.model_form import bloomerp_modelform_factory
from bloomerp.models.forms.form import Form
from bloomerp.services.create_view_services import get_addable_fields
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.views.base import BaseBloomerpView
from bloomerp.views.detail.base_detail import BaseBloomerpDetailView
from bloomerp.views.mixins.layout_form_mixin import BloomerpLayoutFormMixin

@router.register(
    path="builder",
    name="Form Builder",
    url_name="form_builder",
    route_type="detail",
    models=[Form]
)
class BuilderView(BloomerpLayoutFormMixin, BaseBloomerpDetailView):
    model = Form
    template_name = "form_views/builder.html"
    layout_mode = "form"

    def has_permission(self) -> bool:
        if self.request.user.is_superuser:
            return True
        manager = UserPermissionManager(self.request.user)
        form = self.get_object()
        return manager.has_access_to_object(
            form,
            create_permission_str(form, "change"),
        )

    def get_layout_content_type(self) -> ContentType:
        return self.object.content_type

    def get_target_model(self):
        return self.get_layout_content_type().model_class()

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

    def get_layout_view_permission(self) -> str:
        model = self.get_target_model()
        if model is None:
            return ""
        return create_permission_str(model, "add")

    def get_layout_edit_permission(self) -> str:
        return self.get_layout_view_permission()

    def can_render_unbound_editable_layout_field(self, application_field) -> bool:
        return True

    def get_layout_editable_field_names(self) -> list[str]:
        return list(
            get_addable_fields(
                content_type=self.get_layout_content_type(),
                user=self.request.user,
            ).values_list("field", flat=True)
        )

    def get_model_form_field_names(self) -> list[str]:
        field_names: list[str] = []
        for application_field in get_addable_fields(
            content_type=self.get_layout_content_type(),
            user=self.request.user,
        ):
            field_type = application_field.get_field_type_enum().value
            if field_type.editable_without_form_field and not field_type.allow_in_model:
                continue
            if application_field.get_form_field() is None:
                continue
            field_names.append(application_field.field)
        return field_names

    # TODO: This should probs be refactored so that the model form is allowing for one-to-many fields
    def build_layout_form(self):
        target_model = self.get_target_model()
        field_names = self.get_model_form_field_names()
        if target_model is None or not field_names:
            return None
        form_class = bloomerp_modelform_factory(target_model, fields=field_names)
        return form_class()

    def can_change_layout(self) -> bool:
        return True

    def can_delete_layout_object(self) -> bool:
        return False

    def get_context_data(self, **kwargs):
        self.object = self.get_object()
        context = super().get_context_data(**kwargs)
        context["form_object"] = self.object
        context["target_content_type"] = self.get_layout_content_type()
        return context
