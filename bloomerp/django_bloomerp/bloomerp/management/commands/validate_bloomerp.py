from django.core.management.base import BaseCommand

from bloomerp.config.validator import (
    BloomerpConfigurationValidator,
    format_styled_validation_section,
)


class Command(BaseCommand):
    help = "Validate the BloomERP configuration."

    def handle(self, *args, **options):
        validator = BloomerpConfigurationValidator.from_runtime()
        result = validator.validate()

        if not result.sections:
            self.stdout.write(self.style.SUCCESS("No BloomERP validation issues found."))
            return

        for section in result.sections:
            self.stdout.write(format_styled_validation_section(section))

        if result.has_errors():
            self.stderr.write(self.style.ERROR("BloomERP validation failed."))
            raise SystemExit(1)
