from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "Generate modules based on the defined module configurations."

    def handle(self, *args, **options):
        
        self.stdout.write(self.style.SUCCESS('Successfully generated modules'))

