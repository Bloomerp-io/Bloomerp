from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import ApplicationField
from bloomerp.models.definition import get_model_config
from django.db import models
from django import db
from bloomerp.field_types.registry import FIELD_TYPE_REGISTRY
from bloomerp.permissions.manager import ensure_bloomerp_model_permissions
from django.utils.encoding import force_str


def get_registered_field_type_id(field) -> str:
    """Recognize reverse relations and registered subclasses before Django fallback."""
    if field.name == "files":
        return FIELD_TYPE_REGISTRY.FILES_RELATION_FIELD.id
    if field.auto_created and field.is_relation:
        if field.one_to_many:
            return FIELD_TYPE_REGISTRY.ONE_TO_MANY_FIELD.id
        if field.one_to_one:
            return FIELD_TYPE_REGISTRY.ONE_TO_ONE_FIELD.id
        return FIELD_TYPE_REGISTRY.MANY_TO_MANY_FIELD.id

    definition = FIELD_TYPE_REGISTRY.get_from_model_field_cls(type(field))
    if definition is not None:
        return definition.id
    return field.get_internal_type()


class Command(BaseCommand):
    help = 'Sync properties with @property decorator and fields in a Django model to ApplicationField'

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Register output controls for application-field synchronization."""
        parser.add_argument(
            '--suppress-output',
            '--surpress-output',
            action='store_true',
            dest='suppress_output',
            help='Do not write non-error command output.',
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Synchronize field metadata and explicitly configured rendering overrides."""
        suppress_output = bool(options.get('suppress_output'))

        if not suppress_output:
            self.stdout.write(self.style.SUCCESS('Starting to sync ApplicationField model'))

        created_permissions = ensure_bloomerp_model_permissions()
        if created_permissions and not suppress_output:
            self.stdout.write(
                self.style.SUCCESS(f'Created {created_permissions} missing model permissions')
            )

        # Get all models in the project
        model_list = apps.get_models()

        for Model in model_list:
            current_field_names = []  # To track existing field names in the model
            Model : models.Model
            
            try:
                if hasattr(Model, '_meta'):
                    def serialize_choice_value(value: Any) -> Any:
                        """Convert nested choice values into JSON-compatible data."""
                        if value is None or isinstance(value, (bool, int, float, str)):
                            return value
                        if isinstance(value, (list, tuple)):
                            return [serialize_choice_value(item) for item in value]
                        if isinstance(value, dict):
                            return {
                                force_str(key): serialize_choice_value(item)
                                for key, item in value.items()
                            }
                        return force_str(value)

                    def serialize_choices(choices: Any) -> Any:
                        """Convert choices to JSON-serializable values.

                        Handles choices of form (value, label) and colored choices
                        of form (value, label, color).
                        """
                        serialized = []
                        try:
                            for c in choices:
                                if not isinstance(c, (list, tuple)):
                                    serialized.append(serialize_choice_value(c))
                                    continue
                                if len(c) == 2:
                                    serialized.append((serialize_choice_value(c[0]), force_str(c[1])))
                                elif len(c) == 3:
                                    serialized.append((serialize_choice_value(c[0]), force_str(c[1]), serialize_choice_value(c[2])))
                                else:
                                    # Fallback: convert all choice elements to JSON-safe values.
                                    new = [serialize_choice_value(x) for x in c]
                                    serialized.append(tuple(new))
                        except Exception:
                            return choices
                        return serialized
                    #----------------------------------------------
                    # Processing properties with @property decorator
                    #----------------------------------------------
                    property_list = [
                        {'field_name': attr, 'field_type': 'Property'}
                        for attr in dir(Model)
                        if isinstance(getattr(Model, attr), property)
                    ]
                    
                    #----------------------------------------------
                    # Processing fields in the model
                    #----------------------------------------------
                    field_list = []
                    fields = Model._meta.get_fields()

                    for field in fields:
                        try:
                            meta = {}
                            db_column = db_table = db_field_type = None
                            field_type = get_registered_field_type_id(field)

                            # UUID-backed primary keys should not become selectable
                            # ApplicationFields for CRUD layouts or permissions.
                            try:
                                # Get database column for field
                                if hasattr(field, 'db_column') or hasattr(field, 'column'):
                                    if field.db_column is not None:
                                        db_column = field.db_column
                                        db_table = Model._meta.db_table # Save db table
                                        db_field_type = field.db_type(db.connection)
                                    else:
                                        db_column = field.column
                                        db_table = Model._meta.db_table
                                        db_field_type = field.db_type(db.connection)

                                    # Check if the field_type is none
                                    if db_field_type is None:
                                        db_column = None
                                        db_table = None
                                        db_field_type = None
                                    
                            except Exception as e:
                                db_column = None
                                db_table = None
                                db_field_type = None
                                
                                    
                            #----------------------------------------------
                            # Processing relation fields
                            #----------------------------------------------
                            if getattr(field, "is_relation", False) and getattr(field, "related_model", None):
                                meta['related_model'] = ContentType.objects.get_for_model(field.related_model).pk

                            #----------------------------------------------
                            # Processing one-to-one and many-to-one fields
                            #----------------------------------------------
                            if field.auto_created:
                                meta['auto_created'] = True
                                if field.one_to_one:
                                    field_type = 'OneToOneField'
                                    
                                if field.many_to_one:
                                    field_type = 'ManyToOneField'
                                
                                if field.one_to_many:
                                    field_type = 'OneToManyField'

                            #----------------------------------------------
                            # Processing status field
                            #----------------------------------------------
                            if field_type == FIELD_TYPE_REGISTRY.STATUS_FIELD.id:
                                try:
                                    meta['choices'] = serialize_choices(getattr(field, 'choices', []))
                                    meta['colored_choices'] = serialize_choices(getattr(field, 'colored_choices', []))
                                    meta['colors'] = {force_str(choice[0]): choice[2] for choice in meta.get('colored_choices', []) if len(choice) > 2}
                                except Exception:
                                    pass

                            #----------------------------------------------
                            # Processing CharField
                            #----------------------------------------------
                            if field_type == FIELD_TYPE_REGISTRY.CHAR_FIELD.id:
                                # Check if field has choices
                                if hasattr(field, 'flatchoices'):
                                    meta['choices'] = serialize_choices(getattr(field, 'flatchoices', []))


                            field_info = {
                                'field_name': field.name,
                                'field_type': field_type,
                                'meta': meta,
                                'db_column' : db_column,
                                'db_field_type' : db_field_type,
                                'db_table' : db_table
                            }
                            field_list.append(field_info)
                            current_field_names.append(field.name)  # Track field name
                        except Exception as exc:
                            # Never interpret a failed inspection as a deleted field.
                            raise CommandError(
                                f"Could not inspect {Model._meta.label}.{field.name}: {exc}"
                            ) from exc

                    content_type_id = ContentType.objects.get_for_model(Model).id
                    all_fields = property_list + field_list

                    config = get_model_config(Model)
                    field_settings = {
                        item.field: item for item in config.field_settings
                    } if config else {}

                    # Sync fields to ApplicationField
                    for field_info in all_fields:
                        field_name = field_info['field_name']
                        current_field_names.append(field_name)  # Track property name
                        field_type = field_info['field_type']
                        meta = field_info.get('meta', None)
                        db_field_type = field_info.get('db_field_type')
                        db_column = field_info.get('db_column')
                        db_table = field_info.get('db_table')


                        related_model = None
                        if meta and 'related_model' in meta:
                            related_model = ContentType.objects.get(pk=meta['related_model'])
                        
                        rendering_defaults = {}
                        if field_name in field_settings:
                            rendering_defaults["advanced_rendering"] = field_settings[field_name].advanced_rendering

                        try:
                            ApplicationField.objects.update_or_create(
                                content_type_id=content_type_id,
                                field=field_name,
                                defaults={
                                    **rendering_defaults,
                                    'field_type': field_type,
                                    'meta': meta,
                                    'related_model': related_model,
                                    'db_column' : db_column,
                                    'db_table' : db_table,
                                    'db_field_type' : db_field_type
                                })
                        except Exception as e:
                            if not suppress_output:
                                self.stderr.write(self.style.ERROR(f"Meta {meta}"))
                                self.stderr.write(self.style.ERROR(f"Field Type {field_type}"))
                                self.stderr.write(self.style.ERROR(f"Error saving ApplicationField for {Model.__name__}.{field_name}: {e}"))
                        
                    # Delete stale ApplicationField entries
                    stale_entries = ApplicationField.objects.filter(
                        content_type_id=content_type_id
                    ).exclude(field__in=current_field_names)

                    stale_entries.delete()

            except AttributeError as e:
                if suppress_output:
                    continue
                self.stderr.write(self.style.ERROR(f"Error processing model {Model.__name__}: {e}"))


        # Remove all ApplicationFields for which the model no longer exists
        content_type_ids = [ct.id for ct in ContentType.objects.all()]
        stale_entries = ApplicationField.objects.exclude(
            content_type_id__in=content_type_ids
        )
        stale_entries.delete()

        if not suppress_output:
            self.stdout.write(self.style.SUCCESS('ApplicationField model synced successfully'))
        
