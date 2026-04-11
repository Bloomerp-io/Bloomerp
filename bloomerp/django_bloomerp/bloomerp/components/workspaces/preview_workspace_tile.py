import json
from typing import Any

from django.http import HttpRequest
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _

from bloomerp.forms.workspaces import DEFAULT_TILE_ICON, TileMetadataForm
from bloomerp.router import router
from bloomerp.services.sql_services import DatabaseTable
from bloomerp.services.user_services import get_data_view_fields, get_user_list_view_preference
from bloomerp.views.view_mixins.wizard import BaseStateOrchestrator
from bloomerp.views.workspace.create_tile import (
    CREATE_TILE_SESSION_KEY,
    TILE_DESCRIPTION_SESSION_KEY,
    TILE_ICON_SESSION_KEY,
    TILE_NAME_SESSION_KEY,
)
from bloomerp.workspaces import orchestrator
from bloomerp.workspaces.analytics_tile.model import (
    AnalyticsTileConfig,
    AnalyticsTileType,
    get_field_options_form_factory,
    is_field_definition_allowed,
    options_form_factory,
)
from bloomerp.workspaces.analytics_tile.utils import get_primitive_field_icon
from bloomerp.workspaces.base import BaseTileConfig
from bloomerp.workspaces.dataview_tile.model import DataViewTileConfig, build_preview_preference
from bloomerp.workspaces.links_tile.model import LinkTileConfig
from bloomerp.workspaces.tiles import TileType
from bloomerp.models.users.user_list_view_preference import ViewType
from django.views.generic import TemplateView

@router.register(
    path="components/preview_workspace_tile/",
    name="preview_workspace_tile",
)
class PreviewWorkspaceTile(TemplateView):
    template_name = "components/workspaces/preview_workspace_tile.html"

    def get_tile_metadata(self) -> dict[str, str]:
        orchestrator = self.get_orchestrator()
        return {
            "tile_name": orchestrator.get_session_data(TILE_NAME_SESSION_KEY) or "",
            "tile_description": orchestrator.get_session_data(TILE_DESCRIPTION_SESSION_KEY) or "",
            "tile_icon": orchestrator.get_session_data(TILE_ICON_SESSION_KEY) or DEFAULT_TILE_ICON,
        }

    def get_tile_metadata_form(self, data: dict[str, str] | None = None) -> TileMetadataForm:
        metadata = self.get_tile_metadata()
        initial = {
            "name": metadata["tile_name"],
            "description": metadata["tile_description"],
            "icon": metadata["tile_icon"],
        }

        if data is None:
            return TileMetadataForm(initial=initial)

        merged_data = {
            **initial,
            **{key: value for key, value in data.items() if key in {"name", "description", "icon"}},
        }
        return TileMetadataForm(data=merged_data)

    def persist_tile_metadata(self, values: dict[str, str]) -> bool:
        form = self.get_tile_metadata_form()
        raw_icon = values.get("icon") or self.get_tile_metadata().get("tile_icon") or DEFAULT_TILE_ICON

        try:
            cleaned_icon = form.fields["icon"].clean(raw_icon)
        except Exception:
            cleaned_icon = DEFAULT_TILE_ICON

        orchestrator = self.get_orchestrator()
        orchestrator.set_session_data(TILE_NAME_SESSION_KEY, (values.get("name") or "").strip())
        orchestrator.set_session_data(
            TILE_DESCRIPTION_SESSION_KEY,
            (values.get("description") or "").strip(),
        )
        orchestrator.set_session_data(TILE_ICON_SESSION_KEY, cleaned_icon or DEFAULT_TILE_ICON)
        return True

    def get_orchestrator(self) -> BaseStateOrchestrator:
        """Returns the state orchestrator for the tile creation wizard."""
        return BaseStateOrchestrator(
            self.request,
            CREATE_TILE_SESSION_KEY
        )

    def get_tile_type(self) -> TileType:
        """Returns the tile type definition"""
        orchestrator = self.get_orchestrator()
        tile_type_key = orchestrator.get_session_data("tile_type")
        if not tile_type_key:
            return None

        return TileType.from_key(tile_type_key)

    def render_tile_preview(self, config:BaseTileConfig) -> str:
        """Renders the tile preview based on the current tile configuration in the session."""
        tile_type = self.get_tile_type()
        render_cls = tile_type.value.render_cls
        
        return render_cls.render(config, self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        config = kwargs.get("new_config") or self.get_config()
        message = kwargs.get("message") or None
        message_type = kwargs.get("message_type")

        ctx["tile_builder_template_name"] = self.get_tile_builder_template()
        try:
            ctx["tile_preview_html"] = self.render_tile_preview(config)
        except Exception as e:
            rendering_error = str(e)
            ctx["tile_preview_html"] = f"<div class='text-muted'>Rendering error: {rendering_error}</div>"
            ctx["rendering_error"] = rendering_error
            render_message = _("Rendering error: %(error)s") % {"error": rendering_error}
            message = f"{message} {render_message}".strip() if message else render_message
            message_type = "error"

        ctx.update(
            self.get_extra_context()
        )
        ctx.update(self.get_tile_metadata())
        ctx["tile_metadata_form"] = self.get_tile_metadata_form()
        ctx["config"] = config
        ctx["message"] = message
        ctx["message_type"] = message_type
        ctx["tile_preview_title"] = ctx["tile_name"] or _("Untitled tile")
        ctx["tile_preview_description"] = ctx["tile_description"]
        ctx["tile_preview_icon"] = ctx["tile_icon"] or DEFAULT_TILE_ICON
        return ctx
    
    def get_tile_builder_template(self):
        """Returns the appropriate tile builder template based on the tile type."""
        match self.get_tile_type():
            case TileType.ANALYTICS_TILE:
                return "components/workspaces/tile_builders/analytics_tile_builder.html"
            case TileType.LINKS_TILE:
                return "components/workspaces/tile_builders/links_tile_builder.html"
            # case TileType.DATAVIEW_TILE:
            #     return "components/workspaces/tile_builders/dataview_tile_builder.html"
            case _:
                return "components/workspaces/tile_builders/default_tile_builder.html"

    def get_config(self) -> LinkTileConfig | DataViewTileConfig | AnalyticsTileConfig | Any:
        """
        Returns the tile config
        """
        ModelCls = self.get_tile_type().value.model
        config_dict = self.get_orchestrator().get_session_data("config")
        try:
            config = ModelCls(**config_dict)
        except:
            config = ModelCls.get_default()
        return config

    def get_extra_context(self) -> dict:
        """Returns any extra context needed for rendering the tile preview."""
        extra_context = {}
        config = self.get_config()
        orchestrator = self.get_orchestrator()

        match self.get_tile_type():
            case TileType.ANALYTICS_TILE:
                tile_type_definition = AnalyticsTileType.from_key(config.type)

                # Get the output table
                output_table = DatabaseTable(
                    **orchestrator.get_session_data("output_table")
                )
                for field in output_table.fields:
                    field.icon = get_primitive_field_icon(field.field_type)
                

                extra_context["types"] = [(i, i.value.key == config.type) for i in AnalyticsTileType.__members__.values()]
                extra_context["tile_type_definition"] = tile_type_definition
                extra_context["output_table"] = output_table
                extra_context["has_global_opts"] = (len(tile_type_definition.opts) > 0)

                global_field_type = None
                if config.type == AnalyticsTileType.TWO_DIM_CHART.value.key:
                    x_axis_field = next(iter(config.fields.get("x_axis") or []), None) if config.fields else None
                    output_field = next(
                        (field for field in output_table.fields if field.name == x_axis_field.name),
                        None,
                    ) if x_axis_field else None
                    global_field_type = output_field.field_type if output_field else None

                extra_context["global_opts_form"] = options_form_factory(tile_type_definition.opts, field_type=global_field_type)(
                    initial=config.opts or {},
                )
                available_output_fields = {}
                field_opts_forms = {}

                for draggable_field in tile_type_definition.fields:
                    available_output_fields[draggable_field.key] = [
                        field
                        for field in output_table.fields
                        if is_field_definition_allowed(draggable_field, field.field_type)
                    ]
                    field_opts_forms[draggable_field.key] = {}

                    for added_field in config.fields.get(draggable_field.key, []) if config.fields else []:
                        output_field = next(
                            (field for field in output_table.fields if field.name == added_field.name),
                            None,
                        )
                        field_opts_forms[draggable_field.key][added_field.name] = get_field_options_form_factory(
                            draggable_field,
                            output_field.field_type if output_field else None,
                        )(
                            initial=added_field.opts or {},
                        )

                extra_context["available_output_fields"] = available_output_fields
                extra_context["field_opts_forms"] = field_opts_forms

            case TileType.LINKS_TILE:
                pass
            # TODO
            # case TileType.DATAVIEW_TILE:
            #     extra_context["content_types"] = [
            #         (ct.id, f"{ct.app_label}.{ct.model}")
            #         for ct in ContentType.objects.all().order_by("app_label", "model")
            #     ]

            #     if config.content_type_id:
            #         content_type = ContentType.objects.filter(id=config.content_type_id).first()
            #         if content_type:
            #             base_preference = get_user_list_view_preference(self.request.user, content_type)
                        
            #             extra_context["view_types"] = [
            #                 (view_type, view_type.value == config.view_type)
            #                 for view_type in ViewType
            #             ]
                        

            case _:
                return {}
        
        return extra_context

    def post(self, request:HttpRequest, *args, **kwargs):
        tile_type = self.get_tile_type()

        # Get the values
        values = request.POST.dict()
        operation = values.get("operation")
        data = json.loads(values.get("data") or "{}")
        config = self.get_config()

        # Save the meta data
        if not operation and ({"name", "description", "icon"} & set(values.keys())):
            self.persist_tile_metadata(values)
            kwargs["new_config"] = config
            return self.get(request, *args, **kwargs)
        
        try:
            operation_def = tile_type.value.model.get_operation(operation)
        except KeyError:
            kwargs["new_config"] = config
            kwargs["message"] = _("Operation does not exist")
            kwargs["message_type"] = "error"
            return self.get(request, *args, **kwargs)

        try:
            # Get the new configuration based on the handler
            resp = operation_def.handler.handle(
                self.get_config(),
                operation_def.validation_model(**data),
            )
            
            # Persist config
            orchestrator = self.get_orchestrator()
            orchestrator.set_session_data("config", resp.config.model_dump())

            # Add them to kwargs
            kwargs["new_config"] = resp.config
            kwargs["message"] = resp.message
            kwargs["message_type"] = resp.message_type

        except Exception as e:
            # Case
            kwargs["new_config"] = config
            kwargs["message"] = f"An error occured: {e}"
            kwargs["message_type"] = "error"
        
        return self.get(request, *args, **kwargs)
            