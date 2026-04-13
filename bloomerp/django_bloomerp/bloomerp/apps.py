import os
import sys

from django.apps import AppConfig
from colorama import Fore, Style


class BloomerpApp(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bloomerp"

    def _should_run_startup_validation(self) -> bool:
        if len(sys.argv) > 1 and sys.argv[1] == "validate_bloomerp":
            return False
        if len(sys.argv) > 1 and sys.argv[1] == "runserver":
            return os.environ.get("RUN_MAIN") == "true"
        return True

    def ready(self) -> None:
        from django.core.exceptions import ImproperlyConfigured
        from django.db.utils import OperationalError, ProgrammingError
        from bloomerp.config.validator import validate_runtime_configuration
        from bloomerp.signals.automations import setup_automation_signals
        from bloomerp.modules.definition import module_registry

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
