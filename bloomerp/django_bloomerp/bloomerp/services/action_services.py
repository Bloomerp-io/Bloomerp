"""Resolve and render object and dataview actions."""

import json
import logging
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import PermissionDenied
from django.forms.utils import flatatt
from django.http import HttpRequest, HttpResponse, QueryDict
from django.middleware.csrf import get_token
from django.template.loader import render_to_string
from django.utils.html import conditional_escape
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.safestring import mark_safe
from django.utils.translation import gettext
from django_htmx.http import trigger_client_event

from bloomerp.models.definition import (
    DataviewAction,
    DataviewActionContext,
    DataviewActionDefinition,
    DataviewActionGrouping,
    DataviewHTMLAction,
    ObjectAction,
    ObjectActionContext,
    ObjectActionDefinition,
    ObjectActionGrouping,
    ObjectHTMLAction,
)
from bloomerp.utils.requests import render_message

logger = logging.getLogger(__name__)

ActionContext = ObjectActionContext | DataviewActionContext
ActionDefinition = ObjectActionDefinition | DataviewActionDefinition
ActionButton = ObjectAction | DataviewAction
ActionGroup = ObjectActionGrouping | DataviewActionGrouping
HTMX_REQUEST_ATTRIBUTES = ("hx-get", "hx-post", "hx-put", "hx-patch", "hx-delete")
ACTION_DATAVIEW_PREFERENCE_PARAM = "_action_preference"


def with_dataview_context(url: str, context: DataviewActionContext) -> str:
    """Carry the originating preference and filters to a dataview endpoint."""
    parts = urlsplit(url)
    query = QueryDict(context.querystring, mutable=True)
    if context.preference.pk is not None:
        query[ACTION_DATAVIEW_PREFERENCE_PARAM] = context.preference.pk
    return urlunsplit(parts._replace(query=query.urlencode()))


def render_action_success(
    request: HttpRequest,
    action: ActionButton,
    *,
    content_type_id: int,
    object_id: str | None = None,
) -> HttpResponse:
    """Show the success notice and apply the configured refresh in the originating DataView."""
    response = render_message(
        request, gettext(action.success_message or "Action executed successfully"), "success",
    )
    detail: dict[str, int | str | bool] = {"contentTypeId": content_type_id, "originOnly": True}
    if action.refresh_on_success == "item" and object_id is not None:
        detail["objectId"] = object_id
        trigger_client_event(response, "bloomerp:dataview-record-refresh", detail, after="swap")
    elif action.refresh_on_success == "dataview":
        trigger_client_event(response, "bloomerp:dataview-refresh", detail, after="swap")
    return response


def action_is_visible(action: ActionDefinition, context: ActionContext) -> bool:
    """Evaluate a configured visibility predicate and deny on failure."""
    try:
        return action.should_render_func(context)
    except PermissionDenied:
        return False
    except Exception:
        logger.exception("Visibility check failed for action %s", action.id)
        return False


def find_executable_action(
    actions: Sequence[ActionDefinition],
    action_id: str,
) -> tuple[ActionButton, tuple[ActionGroup, ...]] | None:
    """Find a server action and any enclosing groups whose visibility applies."""
    for action in actions:
        if isinstance(action, (ObjectActionGrouping, DataviewActionGrouping)):
            result = find_executable_action(action.actions, action_id)
            if result is not None:
                button, groups = result
                return button, (action, *groups)
        elif isinstance(action, (ObjectAction, DataviewAction)):
            if action.id == action_id and action.execution_func is not None:
                return action, ()
    return None


def _button_attrs(
    action: ActionButton,
    context: ActionContext,
    execution_url: Callable[[str], str],
    *,
    menu_item: bool,
    selection_only: bool = False,
) -> dict[str, Any] | None:
    """Build the action's attributes with sizing for its surface and menu placement."""
    if menu_item:
        attrs = {
            "class": (
                "flex w-full items-center gap-2 px-4 py-2 text-left text-sm "
                "text-gray-700 hover:bg-gray-100 focus:bg-gray-100"
            ),
            "role": "menuitem",
            "@click": "$dispatch('dropdown-close')",
        }
    elif isinstance(context, DataviewActionContext):
        attrs = {
            "class": "btn btn-xs btn-ghost" if selection_only
            else "btn btn-sm btn-secondary w-full justify-center sm:w-auto",
        }
    elif context.surface == "dataview_item":
        attrs = {"class": f"btn btn-{context.button_size} btn-ghost"}
    else:
        attrs = {"class": f"btn btn-{context.button_size} btn-secondary"}

    attrs.update({"type": "button", **action.get_button_attrs(context)})
    if isinstance(context, ObjectActionContext):
        attrs["data-object-action-id"] = action.id
        attrs["data-no-row-click"] = ""
    if not action.label:
        attrs.setdefault("aria-label", action.id.replace("_", " ").replace("-", " "))

    if "href" in attrs:
        href = attrs["href"]
        if not isinstance(href, str) or not href:
            return None
        attrs.pop("type", None)
        return attrs

    request_attr = next((key for key in HTMX_REQUEST_ATTRIBUTES if key in attrs), None)
    if request_attr is None:
        endpoint = action.endpoint
        url = endpoint(context) if callable(endpoint) else endpoint
        if action.execution_func is not None:
            url = execution_url(action.id)
        if not url:
            return attrs
        request_attr = f"hx-{action.method.lower()}"
        attrs[request_attr] = url

    url = attrs[request_attr]
    if not isinstance(url, str) or not url:
        return attrs
    request = context.request
    default_target = (
        "#data-view-data-section"
        if isinstance(context, DataviewActionContext) and (
            not action.refresh_on_success or action.execution_func is None
        )
        else "#object-actions-target"
    )
    attrs.setdefault("hx-target", default_target)
    attrs.setdefault("hx-swap", "innerHTML")
    if request_attr != "hx-get" and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        attrs.setdefault("hx-vals", json.dumps({"csrfmiddlewaretoken": get_token(request)}))
    return attrs


def render_action(
    action: ActionDefinition,
    context: ActionContext,
    template_context: dict[str, Any],
    execution_url: Callable[[str], str],
    *,
    menu_item: bool = False,
    selection_only: bool | None = None,
) -> str:
    """Render a visible action or a non-empty dropdown with its trigger size."""
    child_selection_only = selection_only
    if isinstance(action, DataviewActionGrouping):
        if action.requires_selection:
            if selection_only is False:
                return ""
            child_selection_only = None
    elif isinstance(action, (DataviewAction, DataviewHTMLAction)):
        if selection_only is not None and action.requires_selection != selection_only:
            return ""
    if not action_is_visible(action, context):
        return ""
    values = {**template_context, "action": action, "action_context": context, "menu_item": menu_item}
    if isinstance(action, (ObjectActionGrouping, DataviewActionGrouping)):
        items = [
            mark_safe(markup)
            for child in action.actions
            if (markup := render_action(
                child, context, template_context, execution_url,
                menu_item=True, selection_only=child_selection_only,
            )).strip()
        ]
        if not items:
            return ""
        label = conditional_escape(gettext(action.label)) if action.label else ""
        group_button_size = "xs" if selection_only else action.button_size
        if group_button_size is None and isinstance(context, ObjectActionContext):
            group_button_size = context.button_size
        values.update({
            "items": items,
            "submenu": menu_item,
            "dataview_group": isinstance(action, DataviewActionGrouping),
            "selection_only": selection_only,
            "group_button_size": group_button_size,
            "group_label": label,
            "group_name": label or gettext("More actions"),
            "group_icon": action.icon or ("fa-solid fa-ellipsis" if not action.label else ""),
        })
        template = "components/objects/actions/group.html"
    elif isinstance(action, (ObjectHTMLAction, DataviewHTMLAction)):
        if action.context_func is not None:
            values.update(action.context_func(context))
        template = action.template_name
    else:
        attrs = _button_attrs(
            action, context, execution_url,
            menu_item=menu_item, selection_only=selection_only is True,
        )
        if attrs is None:
            return ""
        values["action_tag"] = "a" if "href" in attrs else "button"
        values["button_attributes"] = flatatt(attrs)
        template = "components/objects/actions/button.html"
    return render_to_string(template, values, request=context.request)
