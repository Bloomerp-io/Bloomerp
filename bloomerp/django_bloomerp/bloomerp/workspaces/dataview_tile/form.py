from bloomerp.models.users.user_list_view_preference import ViewTypeEnum


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
        choices=ViewTypeEnum.choices(),
        required=True,
    )
