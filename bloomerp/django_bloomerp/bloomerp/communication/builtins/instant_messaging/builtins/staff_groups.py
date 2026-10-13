"""Bloomerp staff-group controls, authorization and native creation behavior."""

import json
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _
from bloomerp.communication.builtins.instant_messaging.definition import (
    IMCreationAction,
    IMProviderDefinition,
)
from bloomerp.communication.builtins.instant_messaging.controller import IMController
from bloomerp.components.communication.instant_messaging.conversation import (
    render_conversation,
)
from bloomerp.filters.utils import dict_to_filter
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget


def can_create_staff_group(request: HttpRequest) -> bool:
    """Allow active staff to create native groups independently of user-model policies."""
    return request.user.is_active and request.user.is_staff


def create_staff_group(
    request: HttpRequest, provider: IMProviderDefinition, action: IMCreationAction
) -> HttpResponse:
    """Render the existing staff picker or create a group after dispatcher authorization."""
    user_model = get_user_model()
    form = forms.Form(request.POST if request.method == "POST" else None)
    form.fields["name"] = forms.CharField(label=_("Group name"), max_length=255)
    form.fields["recipients"] = forms.ModelMultipleChoiceField(
        label=_("Participants"),
        queryset=user_model.objects.filter(is_active=True, is_staff=True)
        .exclude(pk=request.user.pk)
        .order_by(user_model.USERNAME_FIELD),
        widget=ForeignFieldWidget(
            model=user_model,
            attrs={
                "is_m2m": True,
                "class": "input w-full",
                "choices_filter": json.dumps(
                    [
                        dict_to_filter(
                            {"is_active": True, "is_staff": True},
                            model=user_model,
                        ).model_dump(mode="json")
                    ]
                ),
                "aria_label": _("Participants"),
            },
        ),
    )
    if request.method == "POST" and form.is_valid():
        try:
            chat = IMController(request.user).create_internal_group(
                form.cleaned_data["name"],
                [str(user.pk) for user in form.cleaned_data["recipients"]],
            )
        except (ValueError, ValidationError) as error:
            form.add_error(None, error)
        else:
            response = render_conversation(request, chat.pk)
            response["HX-Retarget"] = "#im-conversation-host"
            response["HX-Reswap"] = "innerHTML"
            response["HX-Trigger"] = json.dumps(
                {
                    "im:conversation-opened": {
                        "id": str(chat.pk),
                        "target": "[bloomerp-component='bloomerp:messaging-panel']",
                    }
                }
            )
            return response
    return render(
        request,
        "components/communication/instant_messaging/create_group.html",
        {"form": form, "provider": provider, "action": action},
    )
