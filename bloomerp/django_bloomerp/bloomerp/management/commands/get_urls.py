# myapp/management/commands/list_urls.py

from django.core.management.base import BaseCommand
from django.urls import get_resolver, URLPattern, URLResolver

class Command(BaseCommand):
    help = 'Saves all URLs with their paths and names to a text file'

    def handle(self, *args, **kwargs):
        url_patterns = get_resolver().url_patterns
        with open('urls.txt', 'w') as file:
            self.write_patterns(file, url_patterns)
        self.stdout.write(self.style.SUCCESS('Successfully saved URLs to urls.txt'))

    def write_patterns(self, file, patterns, prefix=''):
        for pattern in patterns:
            if isinstance(pattern, URLPattern):
                name = pattern.name if pattern.name else 'Unnamed'
                file.write(f'{name}: {prefix}{pattern.pattern}\n')
            elif isinstance(pattern, URLResolver):
                self.write_patterns(file, pattern.url_patterns, prefix + str(pattern.pattern))