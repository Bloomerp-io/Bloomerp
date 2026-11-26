from collections.abc import Callable, Mapping
from datetime import date, time
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.urls import reverse
from django.utils.translation import gettext

from bloomerp.models.actions.permissions import can_add_model
from bloomerp.models.definition import (
    ActionDrawerSize,
    ObjectAction,
    ObjectActionContext,
    ObjectActionTarget,
)
from bloomerp.tokens import (
    REQUEST_TOKEN_QUERY_KEYS,
    RequestToken,
    request_context_attributes,
)

from .target import targeted_object_action

type InitialValues = Mapping[str, str | int | float | Decimal | UUID | date | time | None]


def create_object_action(
    model: type[Model] | str,
    *,
    target: ObjectActionTarget = "modal",
    initial: InitialValues | Callable[[ObjectActionContext], InitialValues] | None = None,
    id: str | None = None,
    label: str | None = None,
    icon: str | None = "fa fa-plus",
    title: str | None = None,
    size: ActionDrawerSize = "md",
    button_attrs: dict[str, Any] | Callable[[ObjectActionContext], dict[str, Any]] | None = None,
    should_render_func: Callable[[ObjectActionContext], bool] | None = None,
    request_token: RequestToken | Callable[[ObjectActionContext], RequestToken | None] | None = None,
) -> ObjectAction:
    """Open a prefilled create form in the main content, shared modal, or shared drawer.

    Initial values can be fixed or computed from the source record and its action
    context. Use primary keys for relations and the form's input names for inline
    fields (for example, `contact_roles__0__contact`). Values of None are omitted.
    Supply a request token to configure the create form and any scoped grants.
    The action requires add permission on the target model.
    """
    if isinstance(model, str):
        app_label, separator, model_name = model.partition(".")
        if not app_label or not separator or not model_name or "." in model_name:
            raise ValueError("Use an app_label.ModelName reference for the target model.")
        verbose_name = model_name
    else:
        model_name = model._meta.model_name
        verbose_name = model._meta.verbose_name

    def target_model() -> type[Model]:
        """Resolve a deferred reference after Django has loaded its models."""
        return apps.get_model(model) if isinstance(model, str) else model

    def endpoint(context: ObjectActionContext) -> str:
        """Pass initial values to the existing create view."""
        resolved_model = target_model()
        if target == "main":
            from bloomerp.utils.models import get_create_view_url

            url = reverse(get_create_view_url(resolved_model))
        else:
            content_type = ContentType.objects.get_for_model(resolved_model)
            url = reverse("components_create_object", kwargs={"content_type_id": content_type.pk})
        values = initial(context) if callable(initial) else initial
        query = {
            key: value for key, value in (values or {}).items()
            if value is not None and key not in REQUEST_TOKEN_QUERY_KEYS
        }
        return f"{url}?{urlencode(query)}" if query else url

    def request_button_attrs(context: ObjectActionContext) -> dict[str, Any]:
        """Put the create form layout on the opening request's context."""
        attrs = dict((button_attrs(context) if callable(button_attrs) else button_attrs) or {})
        token = request_token(context) if callable(request_token) else request_token
        if token is not None:
            attrs.update(request_context_attributes(context.request, token))
        return attrs

    def can_render(context: ObjectActionContext) -> bool:
        """Apply the target model's add permission and any caller-supplied restriction."""
        return (
            (request_token is None or context.request.user.is_authenticated)
            and can_add_model(context.request, target_model())
            and (should_render_func is None or should_render_func(context))
        )

    return targeted_object_action(
        target=target,
        id=id if id is not None else f"create-{model_name.lower()}",
        label=label if label is not None else gettext("Create %(model)s") % {"model": verbose_name},
        icon=icon,
        endpoint=endpoint,
        should_render_func=can_render,
        title=title,
        size=size,
        button_attrs=request_button_attrs,
    )
