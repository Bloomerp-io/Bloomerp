"""Export the dataview records using its search and filters."""

from django.utils.translation import gettext_noop

from bloomerp.models.definition import DataviewActionContext, DataviewModalAction


def dataview_export_url(context: DataviewActionContext) -> str:
    """Open the export form with the active search and filters for this model."""
    from django.urls import reverse

    from bloomerp.dataviews.registry import DATAVIEW_REGISTRY

    url = reverse(
        "components_export_objects", kwargs={"content_type_id": context.content_type.pk}
    )
    query = context.request.GET.copy()
    renderer = DATAVIEW_REGISTRY.get(context.preference.view_type)
    reserved = renderer.renderer_cls.get_reserved_query_params() if renderer else set()
    for key in {"page", "_component_id"} | reserved:
        query.pop(key, None)
    return f"{url}?{query.urlencode()}" if query else url


def export_action() -> DataviewModalAction:
    """Open the shared export modal for the current dataview."""
    return DataviewModalAction(
        id="export",
        label=gettext_noop("Export"),
        icon="fa-solid fa-download",
        endpoint=dataview_export_url,
        modal_id="export-objects-modal",
        button_attrs={"hx-push-url": "false"},
        shortcut="mod+4",
    )
