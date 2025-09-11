from django.apps import AppConfig

class BloomerpConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bloomerp"

    def ready(self) -> None:
        
        # import bloomerp.signals
        from bloomerp.utils.config import BloomerpConfigChecker
        from shared_utils.registries.route_registry import router
        checker = BloomerpConfigChecker()
        checker.check()
        
        


