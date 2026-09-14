from django import forms
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _

from bloomerp.models.definition import (
    get_default_dataview_actions,
    get_model_config,
)
from bloomerp.models.users.user_list_view_preference import UserListViewPreference
from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.services.preference_services import PreferenceManager
from bloomerp.widgets.code_editor_widget import CodeEditorWidget
from bloomerp.widgets.filter_widget import FilterWidget
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget

EXCLUDED_DATAVIEW_TILE_ACTION_IDS = {
    "display-options",
    "select-preference",
}


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
    actions = forms.MultipleChoiceField(
        label=_("Actions"),
        help_text=_("Choose which actions will be rendered in the toolbar."),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    initial_query_params = forms.JSONField(
        label=_("Initial query parameters"),
        help_text=_(
            "Optional query parameters applied when rendering the data view, "
            'for example {"status": "active"}.'
        ),
        required=False,
    )

    def clean_initial_query_params(self) -> dict:
        """Require query parameters to be represented by a JSON object."""
        initial_query_params = self.cleaned_data.get("initial_query_params") or {}
        if not isinstance(initial_query_params, dict):
            raise forms.ValidationError(
                _("Initial query parameters must be a JSON object.")
            )
        return initial_query_params

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

            content_type = self.fields["content_type_id"].queryset.get(
                pk=content_type_id
            )
            model = content_type.model_class()
            model_config = get_model_config(model) if model is not None else None
            if model_config and model_config.model_view_settings:
                actions = model_config.model_view_settings.dataview_actions
            else:
                actions = get_default_dataview_actions()

            actions = [
                action
                for action in actions
                if action.id not in EXCLUDED_DATAVIEW_TILE_ACTION_IDS
            ]
            self.fields["actions"].choices = [
                (
                    action.id,
                    getattr(action, "label", None)
                    or action.id.replace("-", " ").title(),
                )
                for action in actions
            ]
            if self.initial.get("actions") is None:
                self.initial["actions"] = [action.id for action in actions]

            self.fields["initial_query_params"].widget = FilterWidget(
                model=content_type.model_class()
            )