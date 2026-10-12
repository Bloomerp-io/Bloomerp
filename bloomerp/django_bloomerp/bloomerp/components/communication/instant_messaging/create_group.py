"""Internal group creation using the shared form and conversation renderer."""

import json

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from bloomerp.communication.builtins.instant_messaging.controller import IMController
from bloomerp.filters.utils import dict_to_filter
from bloomerp.router import router
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget

from .conversation import render_conversation


@router.register(
    path="components/communication/im/groups/create/",
    url_name="components_im_create_group",
)
@login_required
@require_http_methods(["GET", "POST"])
def create_group(request: HttpRequest) -> HttpResponse:
    """Render a Crispy staff picker or create the selected internal group."""
    if not request.user.is_active or not request.user.is_staff:
        raise PermissionDenied
    user_model = get_user_model()
    form = forms.Form(request.POST if request.method == "POST" else None)
    form.fields["name"] = forms.CharField(label="Group name", max_length=255)
    form.fields["recipients"] = forms.ModelMultipleChoiceField(
        label="Participants",
        queryset=user_model
        .objects.filter(is_active=True, is_staff=True)
        .exclude(pk=request.user.pk)
        .order_by(user_model.USERNAME_FIELD),
        widget=ForeignFieldWidget(
            model=user_model,
            attrs={
                "is_m2m": True,
                "class": "input w-full",
                "choices_filter": json.dumps([dict_to_filter(
                    {"is_active": True, "is_staff": True}, model=user_model,
                ).model_dump(mode="json")]),
                "aria_label": "Participants",
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
                {"im:conversation-opened": {"id": str(chat.pk)}}
            )
            return response
    return render(
        request,
        "components/communication/instant_messaging/create_group.html",
        {"form": form},
    )
