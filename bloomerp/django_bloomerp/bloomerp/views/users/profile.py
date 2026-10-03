from functools import cached_property
from typing import Any

from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.users.user import User
from bloomerp.models.users.user_object_layout_preference import UserObjectLayoutPreference
from bloomerp.router import router
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.views.generic.detail.base import BaseBloomerpDetailView
from bloomerp.views.mixins.application_field_layout_form_mixin import (
    ApplicationFieldLayoutFormMixin,
)
from bloomerp.views.mixins.layout_mixin import LayoutBinding

from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic.edit import UpdateView
from django.db.models import QuerySet


@router.register(
    path="my-profile/",
    models=User,
    route_type="model",
    name="Profile",
    description="Overview of profile",
    url_name="my_profile_overview"
)
class BloomerpProfileView(ApplicationFieldLayoutFormMixin, BaseBloomerpDetailView, UpdateView):
    template_name = 'views/users/profile.html'
    fields = ['first_name', 'last_name', 'date_view_preference', 'datetime_view_preference']
    success_url = reverse_lazy('users_my_profile_overview')
    apply_permissions = False

    def has_permission(self) -> bool:
        """Allow an authenticated user to edit only their own profile fields."""
        return True

    def get_object(self, queryset: QuerySet[User] | None = None) -> User:
        """Return the signed-in user represented by this profile page."""
        return self.request.user

    def get_layout_binding(self) -> LayoutBinding:
        """Use the user's saved layout preference as the layout owner."""
        content_type = ContentType.objects.get_for_model(User)
        return LayoutBinding(
            owner=PreferenceManager(self.request.user).get_or_create_selected(
                UserObjectLayoutPreference,
                scope={"content_type_id": content_type.pk},
            ),
            target_content_type=content_type,
        )

    def get_view_permission_str(self) -> str:
        """Identify the model permission used for viewing user fields."""
        return "view_user"

    def get_change_permission_str(self) -> str:
        """Identify the model permission used for changing user fields."""
        return "change_user"

    @cached_property
    def profile_layout(self) -> FieldLayout:
        """Build two small rows from the profile's ApplicationField records."""
        fields_by_name = {
            field.field: field
            for field in ApplicationField.get_for_model(User).filter(field__in=self.fields)
        }

        def items_for(*names: str) -> list[LayoutItem]:
            """Create layout items for registered fields in the requested order."""
            return [
                LayoutItem(id=fields_by_name[name].pk)
                for name in names
                if name in fields_by_name
            ]

        return FieldLayout(rows=[
            LayoutRow(
                columns=2,
                title="General information",
                items=items_for("first_name", "last_name"),
            ),
            LayoutRow(
                columns=2,
                title="Display preferences",
                items=items_for("date_view_preference", "datetime_view_preference"),
            ),
        ])

    def get_layout(self) -> FieldLayout:
        """Use the focused profile layout for both rendering and widgets."""
        return self.profile_layout

    def get_form(self, form_class: type[ModelForm] | None = None) -> ModelForm:
        """Bind the update form and apply the layout's widget configuration."""
        cached_form = getattr(self, "_layout_form", None)
        if cached_form is None:
            cached_form = UpdateView.get_form(self, form_class)
            self._layout_form = self.apply_layout_widget_config(cached_form)
        return self._layout_form

    def get_form_kwargs(self) -> dict[str, Any]:
        """Ensure submitted changes update the signed-in user."""
        kwargs = super().get_form_kwargs()
        kwargs['instance'] = self.request.user
        return kwargs

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Save valid profile fields and show errors in the layout otherwise."""
        self.object = self.get_object()
        form = self.get_form()
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect(self.success_url)
        return self.form_invalid(form)
