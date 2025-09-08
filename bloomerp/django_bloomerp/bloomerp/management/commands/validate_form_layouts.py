from django.core.management.base import BaseCommand
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import ApplicationField
from django.db import models
from django import db

class Command(BaseCommand):
    help = 'Validates the form layouts for all models.'

    def handle(self, *args, **options):
        model_list = apps.get_models()

        incorrect_number = 0

        for Model in model_list:
            if hasattr(Model, 'form_layout'):
                correct, missing_fields = Model._validate_form_layout()

                if not correct:
                    self.stdout.write(self.style.ERROR(f'Form layout for {Model.__name__} is incorrect. Missing fields: {missing_fields}'))
                    incorrect_number += 1

        if incorrect_number == 0:
            self.stdout.write(self.style.SUCCESS('All form layouts are correct!'))
        else:
            self.stdout.write(self.style.ERROR(f'{incorrect_number} form layouts are incorrect!'))
        