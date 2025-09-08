from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate links for all views in the application'

    def handle(self, *args, **options):
        from bloomerp.urls import custom_router_handler
        custom_router_handler.generate_links()

        self.stdout.write(self.style.SUCCESS('Successfully generated links'))

