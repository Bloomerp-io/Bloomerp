from django import forms
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _

from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget


class DataViewTileForm(forms.Form):
    content_type_id = forms.ModelChoiceField(
        label=_("Model"),
        queryset=ContentType.objects.none(),
        required=True,
        widget=ForeignFieldWidget(
            model=ContentType,
            attrs={"class": "input w-full"},
        ),
    )
    list_view_preference_id = forms.ModelChoiceField(
        label=_("List view preference"),
        queryset=UserListViewPreference.objects.none(),
        required=False,
        empty_label=_("Use current preference"),
        widget=forms.Select(attrs={"class": "select w-full"}),
    )

    def __init__(self, *args, user: AbstractBloomerpUser, **kwargs) -> None:
        """Build content-type and saved-preference choices available to the user."""
        super().__init__(*args, **kwargs)
        self.fields["content_type_id"].queryset = UserPolicyManager(
            user
        ).get_accessible_content_types(
            BloomerpPermission.VIEW
        )

        content_type_id = self.data.get("content_type_id") if self.is_bound else None
        if not content_type_id:
            content_type_id = self.initial.get("content_type_id")

        try:
            content_type_is_accessible = bool(content_type_id) and self.fields[
                "content_type_id"
            ].queryset.filter(pk=content_type_id).exists()
        except (TypeError, ValueError):
            content_type_is_accessible = False

        if content_type_is_accessible:
            self.fields["list_view_preference_id"].queryset = PreferenceManager(
                user
            ).get_available(
                UserListViewPreference,
                {"content_type_id": content_type_id},
            )
