from __future__ import annotations

from functools import lru_cache

from django.apps import AppConfig, apps
from django.utils.encoding import force_str
from django.utils.translation import override

from bloomerp.config.definition import get_bloomerp_config
from bloomerp.i18n.apps import get_app_source_language


def model_verbose_name_in_source_language(model, *, plural: bool = False) -> str:
    """Return a model label in the source language of its owning app.

    Model labels are translated presentation metadata. Routes and API resource
    identifiers that retain the historical verbose-name convention must resolve
    that metadata in a stable language instead of the active request language.
    """

    model_class = model if isinstance(model, type) else model.__class__
    app = apps.get_app_config(model_class._meta.app_label)
    source_language = get_app_source_language(
        app,
        get_bloomerp_config().i18n,
    )
    return _model_verbose_name_in_language(model_class, plural, source_language)


@lru_cache(maxsize=None)
def _model_verbose_name_in_language(model, plural: bool, source_language: str) -> str:
    attribute = "verbose_name_plural" if plural else "verbose_name"
    with override(source_language):
        return force_str(getattr(model._meta, attribute))


def model_messages(app: AppConfig, source_language: str) -> list[dict]:
    """Expose model and field display metadata, including Django's fallbacks."""

    messages: list[dict] = []
    with override(source_language):
        for model in app.get_models():
            model_location = f"{app.label}.{model._meta.model_name}"
            for label in (model._meta.verbose_name, model._meta.verbose_name_plural):
                value = force_str(label)
                if value:
                    messages.append(
                        {"message": value, "locations": [(model_location, None)]}
                    )
            for name in dir(model):
                if not name.startswith("_") and isinstance(getattr(model, name, None), property):
                    messages.append(
                        {
                            "message": name.replace("_", " ").title(),
                            "locations": [(f"{model_location}.{name}", None)],
                        }
                    )
            for field in model._meta.get_fields():
                label = getattr(field, "verbose_name", None)
                if label:
                    declared_label = getattr(field, "_verbose_name", None)
                    display_label = (
                        force_str(declared_label)
                        if declared_label is not None
                        else field.name.replace("_", " ").title()
                    )
                    messages.append(
                        {
                            "message": display_label,
                            "locations": [(f"{model_location}.{field.name}", None)],
                        }
                    )
                help_text = getattr(field, "help_text", None)
                if help_text:
                    messages.append(
                        {
                            "message": force_str(help_text),
                            "locations": [(f"{model_location}.{field.name}", None)],
                        }
                    )
                for choice in getattr(field, "choices", None) or []:
                    if len(choice) >= 2 and choice[1]:
                        messages.append(
                            {
                                "message": force_str(choice[1]),
                                "locations": [(f"{model_location}.{field.name}", None)],
                            }
                        )
    return messages
