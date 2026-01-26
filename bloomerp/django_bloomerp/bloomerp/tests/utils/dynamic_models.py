from django.apps import apps
from django.db import connection, models
from django.test.utils import isolate_apps

from bloomerp.models.base_bloomerp_model import BloomerpModel


def create_test_models(app_label: str, model_defs: dict):
    """
    model_defs = {
        "ModelName": {
            "field_name": models.CharField(...),
            ...
        }
    }
    """
    created_models = {}

    with isolate_apps(app_label):
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

            # Use a simple models.Model base to avoid pulling in project
            # mixins (like UserStampedModelMixin) that reference
            # AUTH_USER_MODEL. Those references can't be resolved inside
            # the isolated app registry used for tests and cause
            # "Related model 'bloomerp.user' cannot be resolved" errors.
            model = type(
                model_name,
                (BloomerpModel,),
                attrs,
            )

            apps.register_model(app_label, model)
            created_models[model_name] = model

        with connection.schema_editor() as schema:
            for model in created_models.values():
                schema.create_model(model)

    return created_models
