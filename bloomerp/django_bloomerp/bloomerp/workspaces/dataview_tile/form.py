from bloomerp.models.users.user_list_view_preference import ViewType


from django import forms
from django.contrib.contenttypes.models import ContentType
from django.forms import Form
from django.utils.translation import gettext_lazy as _


class DataViewTileForm(Form):
    content_type = forms.ModelChoiceField(
        label=_("Model"),
        queryset=ContentType.objects.all(),
        required=True,
    )

    view_type = forms.ChoiceField(
        label=_("View Type"),
        choices=ViewType.choices,
        required=True,
    )