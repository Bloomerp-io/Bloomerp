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

from bloomerp.models.definition import (
    ActionModalSize,
    ObjectActionContext,
    ObjectModalAction,
)
from bloomerp.models.object_actions.permissions import can_add_model

type InitialValues = Mapping[str, str | int | float | Decimal | UUID | date | time | None]


def create_object_action(
    model: type[Model] | str,
    *,
    initial: InitialValues | Callable[[ObjectActionContext], InitialValues] | None = None,
    id: str | None = None,
    label: str | None = None,
    icon: str | None = "fa fa-plus",
    modal_title: str | None = None,
    modal_size: ActionModalSize = "md",
    button_attrs: dict[str, Any] | Callable[[ObjectActionContext], dict[str, Any]] | None = None,
    should_render_func: Callable[[ObjectActionContext], bool] | None = None,
) -> ObjectModalAction:
    """Open a prefilled create form for a model class or an `app_label.ModelName` reference.

    Initial values can be fixed or computed from the source record and its action
    context. Use primary keys for relations and the form's input names for inline
    fields (for example, `contact_roles__0__contact`). Values of None are omitted.
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
        """Encode the initial values using the existing create view's query format."""
        content_type = ContentType.objects.get_for_model(target_model())
        url = reverse("components_create_object", kwargs={"content_type_id": content_type.pk})
        values = initial(context) if callable(initial) else initial
        query = urlencode({key: value for key, value in (values or {}).items() if value is not None})
        return f"{url}?{query}" if query else url

    def can_render(context: ObjectActionContext) -> bool:
        """Apply the target model's add permission and any caller-supplied restriction."""
        return can_add_model(context.request, target_model()) and (
            should_render_func is None or should_render_func(context)
        )

    return ObjectModalAction(
        id=id if id is not None else f"create-{model_name.lower()}",
        label=label if label is not None else gettext("Create %(model)s") % {"model": verbose_name},
        icon=icon,
        endpoint=endpoint,
        should_render_func=can_render,
        modal_title=modal_title,
        modal_size=modal_size,
        button_attrs=button_attrs if button_attrs is not None else {},
    )
