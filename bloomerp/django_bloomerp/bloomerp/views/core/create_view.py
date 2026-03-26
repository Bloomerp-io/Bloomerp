from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.views.generic.edit import CreateView
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.auth import get_user_model
from django.contrib.messages.views import SuccessMessageMixin
from bloomerp.models.files import File
from bloomerp.models.workspaces import Tile, SqlQuery
from bloomerp.models import UserCreateViewPreference
from bloomerp.services.create_view_services import (
    get_create_access_state,
    get_disallowed_submitted_fields,
)
from bloomerp.services.permission_services import UserPermissionManager, create_permission_str
from bloomerp.services.sectioned_layout_services import resolve_create_layout_rows
from bloomerp.utils.models import model_name_plural_underline, get_detail_view_url
from bloomerp.views.mixins import BloomerpModelFormViewMixin, HtmxMixin
from bloomerp.router import router


User = get_user_model()

# TODO: We want to have a button that allows us to hide non required fields.

@router.register(
    path="create",
    name="Create {model}",
    url_name="add",
    description="Create a new object from {model}",
    route_type="model",
    exclude_models=[File, Tile, SqlQuery, User],
)
class BloomerpCreateView(
    PermissionRequiredMixin,
    SuccessMessageMixin,
    HtmxMixin,
    BloomerpModelFormViewMixin,
    CreateView,
):
    template_name = "create_views/bloomerp_create_view.html"
    fields = None
    exclude = []
    success_message = "Object was created successfully."
    module = None
    model = None

    def dispatch(self, request, *args, **kwargs):
        self.model_content_type = ContentType.objects.get_for_model(self.model)
        self.create_access_state = get_create_access_state(content_type=self.model_content_type, user=request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = context.get("form") or self.get_form()

        context["content_type_id"] = self.model_content_type.pk
        context["create_blocked"] = self.create_access_state.is_blocked
        context["create_blocked_message"] = self.create_access_state.blocked_message

        
        preference = UserCreateViewPreference.get_or_create_for_user(self.request.user, self.model_content_type)
        layout = {
            "rows": resolve_create_layout_rows(
                layout=preference.field_layout_obj,
                content_type=self.model_content_type,
                user=self.request.user,
                form=form,
            )
        }
        if not any(row.get("items") for row in layout["rows"]):
            preference.field_layout = self._build_fallback_layout().model_dump()
            preference.save(update_fields=["field_layout"])
            layout = {
                "rows": resolve_create_layout_rows(
                    layout=preference.field_layout_obj,
                    content_type=self.model_content_type,
                    user=self.request.user,
                    form=form,
                )
            }

        context["layout"] = layout
        context["layout_available_items_url"] = f"/components/workspaces/crud_layout_available_fields/?content_type_id={self.model_content_type.pk}&layout_kind=create"
        context["layout_render_item_url"] = "/components/workspaces/crud_layout_render_field/?layout_kind=create"
        return context

    def get_permission_required(self):
        return [f"{self.model._meta.app_label}.add_{self.model._meta.model_name}"]

    def get_success_message(self, cleaned_data):
        return f"{self.object} was created successfully."

    def get_success_url(self):
        try:
            return self.object.get_absolute_url()
        except AttributeError:
            return reverse(get_detail_view_url(self.object), kwargs={"pk": self.object.pk})

    def get_form_class(self):
        allowed_field_names = [field.field for field in self.create_access_state.addable_fields]
        return super().get_form_class_for_fields(allowed_field_names)

    def get_initial(self):
        initial = super().get_initial()
        allowed_field_names = {field.field for field in self.create_access_state.addable_fields}
        for key, value in self.request.GET.items():
            if key in allowed_field_names:
                initial[key] = value
        return initial

    def post(self, request, *args, **kwargs):
        if self.create_access_state.is_blocked:
            form = self.get_form()
            form.add_error(None, self.create_access_state.blocked_message)
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        allowed_field_names = {field.field for field in self.create_access_state.addable_fields}
        denied_fields = get_disallowed_submitted_fields(
            model=self.model,
            submitted_data=self.request.POST,
            allowed_field_names=allowed_field_names,
        )
        if denied_fields:
            form.add_error(None, f"Permission denied for fields: {', '.join(denied_fields)}")
            return self.form_invalid(form)

        permission_manager = UserPermissionManager(self.request.user)
        add_permission = create_permission_str(self.model, "add")
        if not permission_manager.candidate_matches_row_policies(self.model, add_permission, form.cleaned_data):
            form.add_error(None, "You do not have permission to create an object with these values.")
            return self.form_invalid(form)

        return super().form_valid(form)

    def _build_fallback_layout(self):
        from bloomerp.services.create_view_services import get_default_layout

        return get_default_layout(content_type=self.model_content_type, user=self.request.user)

    
