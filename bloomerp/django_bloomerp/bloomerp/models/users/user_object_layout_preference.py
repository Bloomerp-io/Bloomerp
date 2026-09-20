from django.utils.translation import gettext_lazy as _
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from bloomerp.models.definition import BloomerpModelConfig, FieldLayout, ModelViewSettings, StringSearchSettings
from bloomerp.models.definition import get_model_config
from bloomerp.models.mixins.content_layout_model_mixin import ContentLayoutModelMixin
from bloomerp.models.users.base_view_preference import BaseViewPreference
from bloomerp.modules.users import UsersModule


class UserObjectLayoutPreference(ContentLayoutModelMixin, BaseViewPreference):
    """Model to store user preferences for object layouts."""

    class Meta:
        verbose_name = _("User Object Layout Preference")
        verbose_name_plural = _("User Object Layout Preferences")

    bloomerp_config = BloomerpModelConfig(
        module=UsersModule,
        string_search_settings=StringSearchSettings(
            allow_global_search=False,
            string_search_fields=[
                "content_type__model",
                "user__username",
                "user__email"
            ]
        )
    )
    
    @classmethod
    def create_default_for_user(cls, user, **scope) -> "UserObjectLayoutPreference":
        """Materialize configured layouts or create one generated fallback."""
        from bloomerp.services.sectioned_layout_services import create_default_layout

        content_type = ContentType.objects.get(pk=scope["content_type_id"])
        model = content_type.model_class()
        model_config = get_model_config(model) if model is not None else None
        detail_view_settings = (
            model_config.detail_view_settings if model_config is not None else None
        )
        configured_layouts = (
            detail_view_settings.layouts
            if detail_view_settings is not None
            else []
        )
        if configured_layouts:
            return cls.create_configured_defaults(
                user=user,
                content_type=content_type,
                model=model,
                layouts=configured_layouts,
            )

        return cls.objects.create(
            user=user,
            content_type=content_type,
            layout=create_default_layout(model).model_dump(),
            selected=True,
        )

    @classmethod
    def create_configured_defaults(
        cls,
        *,
        user,
        content_type: ContentType,
        model,
        layouts: list[FieldLayout],
    ) -> "UserObjectLayoutPreference":
        """Create every configured layout and return the declared default."""
        from bloomerp.services.sectioned_layout_services import create_default_layout

        selected_preference: UserObjectLayoutPreference | None = None
        with transaction.atomic():
            for layout in layouts:
                preference = cls.objects.create(
                    user=user,
                    content_type=content_type,
                    name=layout.name,
                    selected=layout.is_default,
                    layout=create_default_layout(model, layout=layout).model_dump(),
                )
                if layout.is_default:
                    selected_preference = preference

        if selected_preference is None:
            raise ValueError("Configured detail layouts must define one default.")
        return selected_preference

    @classmethod
    def copy_preference_for_user(
        cls,
        *,
        user,
        source: "UserObjectLayoutPreference",
        name: str,
        scope: dict | None = None,
    ) -> "UserObjectLayoutPreference":
        """Copy an object-layout preference."""
        return cls._create_preference_copy(
            user=user,
            source=source,
            name=name,
            scope=scope,
        )

    def ensure_default_state(self, *, user, content_type: ContentType) -> None:
        if self.layout_obj.rows and any(row.items for row in self.layout_obj.rows):
            return

        from bloomerp.services.sectioned_layout_services import create_default_layout

        model = content_type.model_class()
        if model is None:
            return
        self.layout = create_default_layout(model).model_dump()
        self.save(update_fields=["layout"])
