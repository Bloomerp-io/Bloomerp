import os
import sys

from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.utils.module_loading import autodiscover_modules
from colorama import Fore, Style

from bloomerp.config.definition import BloomerpAppI18nSettings



class BloomerpApp(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bloomerp"
    bloomerp_i18n = BloomerpAppI18nSettings(source_language="en")

    def _should_run_startup_validation(self) -> bool:
        if len(sys.argv) > 1 and sys.argv[1] == "validate_bloomerp":
            return False
        if len(sys.argv) > 1 and sys.argv[1] == "runserver":
            return os.environ.get("RUN_MAIN") == "true"
        return True

    def ready(self) -> None:
        """Initialize registries, model configuration, and signals after models load."""
        from bloomerp.models.definition import BloomerpModelConfig

        # Models are available now; populate built-ins before importing consumers
        # that build catalogs from the registry at module scope.
        from bloomerp.field_types.registry import load_builtin_field_types

        load_builtin_field_types()

        from bloomerp.dataviews.registry import DATAVIEW_REGISTRY

        autodiscover_modules("dataviews", register_to=DATAVIEW_REGISTRY)

        from django.core.exceptions import ImproperlyConfigured
        from django.db.utils import OperationalError, ProgrammingError
        from bloomerp.config.settings import configure_bloomerp_allauth_settings
        from bloomerp.config.validator import validate_runtime_configuration
        from bloomerp.permissions.manager import ensure_bloomerp_model_permissions
        from bloomerp.signals.automation_signals import setup_automation_signals
        from bloomerp.signals.inbox_source_signals import ensure_inbox_source_schedules
        from bloomerp.communication.inbox_sources import InboxSourceRegistry
        from bloomerp.modules.definition import module_registry
        from bloomerp.signals.activity_log_signals import before_save_of_object  # noqa: F401
        from bloomerp.signals.activity_log_signals import after_save_of_object
        from bloomerp.signals.activity_log_signals import before_delete_of_object  # noqa: F401
        from bloomerp.signals.activity_log_signals import after_delete_of_object  # noqa: F401
        from bloomerp.signals import text_editor_image_signals  # noqa: F401
        from bloomerp.lookups.registry import LOOKUP_REGISTRY  # noqa: F401
        from bloomerp.config.utils import set_model_config
        from bloomerp.config.utils import set_detail_view_url
        from django.contrib.auth.models import Group
        from bloomerp.config.builtins.group import GROUP_MODEL_CONFIG
        
        # Set model config of group's model
        set_model_config(Group, GROUP_MODEL_CONFIG)
        set_detail_view_url(Group)

        configure_bloomerp_allauth_settings()

        post_migrate.connect(
            ensure_bloomerp_model_permissions,
            sender=self,
            dispatch_uid="bloomerp.ensure_bloomerp_model_permissions",
        )
        post_migrate.connect(
            ensure_inbox_source_schedules,
            sender=self,
            dispatch_uid="bloomerp.ensure_inbox_source_schedules",
        )

        InboxSourceRegistry.load_defaults()
        InboxSourceRegistry.validate()
        InboxSourceRegistry.connect_signals()

        try:
            setup_automation_signals()
        except (OperationalError, ProgrammingError):
            # Database may not be ready during migrations.
            pass

        # Refresh the module registry
        module_registry.refresh()

        if not self._should_run_startup_validation():
            return

        validation_result = validate_runtime_configuration(include_error_logs=False)
        if validation_result.has_errors():
            header = f"\n{Fore.RED}{Style.BRIGHT}Bloomerp configuration validation failed:{Style.RESET_ALL}"
            error_messages = "\n".join(validation_result.error_messages(styled=True))
            raise ImproperlyConfigured(
                f"{header}\n"
                f"{error_messages}"
            )
