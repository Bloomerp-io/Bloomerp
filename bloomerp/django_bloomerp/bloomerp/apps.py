from django.apps import AppConfig

class BloomerpConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bloomerp"

    def ready(self) -> None:
        from django.db.utils import OperationalError, ProgrammingError
        from bloomerp.signals.automations import setup_automation_signals
        from bloomerp.utils.config import BloomerpConfigChecker
        checker = BloomerpConfigChecker()
        checker.check()
    
        try:
            setup_automation_signals()
        except (OperationalError, ProgrammingError):
            # Database may not be ready during migrations.
            pass
        
        


