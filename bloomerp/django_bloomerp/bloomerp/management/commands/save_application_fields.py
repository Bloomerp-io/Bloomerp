from django.core.management.base import BaseCommand
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from bloomerp.models import ApplicationField
from django.db import models
from django import db

class Command(BaseCommand):
    help = 'Sync properties with @property decorator and fields in a Django model to ApplicationField'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting to sync ApplicationField model'))

        num = 0

        # Get all models in the project
        model_list = apps.get_models()

        for Model in model_list:
            current_field_names = []  # To track existing field names in the model
            Model : models.Model
            try:
                if hasattr(Model, '_meta'):
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
                            # Try-catch block needed to filter out reverse relation fields
                            meta = {}
                            field_type = field.get_internal_type()

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
                            # Processing many-to-many fields and ForeignKeys
                            #----------------------------------------------
                            if field_type in ['ForeignKey', 'ManyToManyField','BloomerpFileField']:
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
                            if field_type == 'StatusField':
                                try:
                                    meta['choices'] = field.choices
                                    meta['colored_choices'] = field.colored_choices
                                    meta['colors'] = {choice[0]: choice[2] for choice in field.colored_choices}
                                except:
                                    pass

                            #----------------------------------------------
                            # Processing CharField
                            #----------------------------------------------
                            if field_type == 'CharField':
                                # Check if field has choices
                                if hasattr(field, 'flatchoices'):
                                    meta['choices'] = field.flatchoices


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
                        except:
                            pass

                    content_type_id = ContentType.objects.get_for_model(Model).id
                    all_fields = property_list + field_list

                    # Sync fields to ApplicationField
                    for field_info in all_fields:
                        field_name = field_info['field_name']
                        current_field_names.append(field_name)  # Track property name
                        field_type = field_info['field_type']
                        meta = field_info.get('meta', None)
                        db_field_type = field_info.get('db_field_type')
                        db_column = field_info.get('db_column')
                        db_table = field_info.get('db_table')


                        if meta:
                            if 'related_model' in meta:
                                related_model = ContentType.objects.get(pk=meta['related_model'])
                        else:
                            related_model = None
                        
                        

                        ApplicationField.objects.update_or_create(
                            content_type_id=content_type_id,
                            field=field_name,
                            defaults={
                                'field_type': field_type,
                                'meta': meta,
                                'related_model': related_model,
                                'db_column' : db_column,
                                'db_table' : db_table,
                                'db_field_type' : db_field_type
                            })

                    # Delete stale ApplicationField entries
                    stale_entries = ApplicationField.objects.filter(
                        content_type_id=content_type_id
                    ).exclude(field__in=current_field_names)

                    stale_entries.delete()

            except AttributeError as e:
                self.stderr.write(self.style.ERROR(f"Error processing model {Model.__name__}: {e}"))


        # Remove all ApplicationFields for which the model no longer exists
        content_type_ids = [ct.id for ct in ContentType.objects.all()]
        stale_entries = ApplicationField.objects.exclude(
            content_type_id__in=content_type_ids
        )
        stale_entries.delete()

        self.stdout.write(self.style.SUCCESS('ApplicationField model synced successfully'))
        


