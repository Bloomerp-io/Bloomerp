from django.apps import apps
from django.db import connection, models

from bloomerp.models.base_bloomerp_model import BloomerpModel


def create_test_models(app_label: str, model_defs: dict, use_bloomerp_base: bool = False) -> dict[str, models.Model | BloomerpModel]:
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

        base = BloomerpModel if use_bloomerp_base else models.Model

        model = type(model_name, (base,), attrs)

        try:
            apps.register_model(app_label, model)
        except Exception:
            # Ignore if the model is already registered (e.g. re-running tests)
            pass

        created_models[model_name] = model

    with connection.schema_editor() as schema:
        for model in created_models.values():
            schema.create_model(model)

    return created_models
