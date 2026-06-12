from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import connection, models

from bloomerp.models.base_bloomerp_model import BloomerpModel
from bloomerp.models.definition import BloomerpModelConfig


def ensure_content_types_for_models(*models_to_register: type[models.Model]) -> None:
    ContentType.objects.clear_cache()
    for model in models_to_register:
        ContentType.objects.get_or_create(
            app_label=model._meta.app_label,
            model=model._meta.model_name,
        )
    ContentType.objects.clear_cache()


def create_test_models(
    app_label: str, 
    model_defs: dict, 
    use_bloomerp_base: bool = False,
    bloomerp_config: BloomerpModelConfig | None = None,
    ) -> dict[str, models.Model | BloomerpModel]:
    """
    model_defs = {
        "ModelName": {
            "field_name": models.CharField(...),
            ...
        }
    }
    """
    created_models = {}

    for model_name, fields in model_defs.items():
        attrs = {
            # set module to a real module path for the app so Django
            # recognizes the model as belonging to that app
            "__module__": f"{app_label}.models",
            **fields,
        }

        # Provide an inner Meta with app_label so Django's ModelBase
        # doesn't require the model to be in INSTALLED_APPS at creation
        Meta = type("Meta", (), {"app_label": app_label})
        attrs["Meta"] = Meta

        if bloomerp_config:
            attrs["bloomerp_config"] = bloomerp_config
        
        base = BloomerpModel if use_bloomerp_base else models.Model

        model = type(model_name, (base,), attrs)
        
        try:
            apps.register_model(app_label, model)
        except Exception:
            # Ignore if the model is already registered (e.g. re-running tests)
            pass

        created_models[model_name] = model

    with connection.schema_editor() as schema:
        existing_tables = set(connection.introspection.table_names())
        for model in created_models.values():
            if model._meta.db_table in existing_tables:
                existing_columns = {
                    column.name
                    for column in connection.introspection.get_table_description(
                        connection.cursor(),
                        model._meta.db_table,
                    )
                }
                for field in model._meta.local_fields:
                    if field.column in existing_columns:
                        continue
                    if getattr(field, "auto_created", False):
                        continue
                    schema.add_field(model, field)
                    existing_columns.add(field.column)
                continue
            schema.create_model(model)
            existing_tables.add(model._meta.db_table)

    ensure_content_types_for_models(*created_models.values())

    return created_models
