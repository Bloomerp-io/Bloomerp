from django.db.models import Model
import random
import string
from datetime import datetime

def random_object_factory(model: Model):
    '''
    Function that generates a random object for a particular model.
    '''
    try:
        # Get the fields of the model
        fields = model._meta.get_fields()

        # Initialize the data dictionary
        data = {}

        # Loop through the fields
        for field in fields:
            if field.get_internal_type() == 'CharField':
                data[field.name] = ''.join(random.choices(string.ascii_letters, k=10))

            elif field.get_internal_type() == 'IntegerField':
                data[field.name] = random.randint(1, 100)

            elif field.get_internal_type() == 'DateTimeField':
                data[field.name] = datetime.now().isoformat()

            elif field.get_internal_type() == 'ForeignKey':
                if field.one_to_many or field.many_to_many:
                    continue

                related_model = field.related_model
                related_instance = related_model.objects.first()
                if related_instance:
                    data[field.name] = related_instance
                else:
                    raise ValueError(f"No instances found for related model {related_model}")

            elif field.get_internal_type() == 'BooleanField':
                data[field.name] = random.choice([True, False])

            elif field.get_internal_type() == 'FloatField':
                data[field.name] = random.uniform(1.0, 100.0)

            elif field.get_internal_type() == 'TextField':
                data[field.name] = ''.join(random.choices(string.ascii_letters + string.digits, k=50))

            elif field.get_internal_type() == 'EmailField':
                data[field.name] = ''.join(random.choices(string.ascii_letters, k=5)) + '@example.com'

            elif field.get_internal_type() == 'URLField':
                data[field.name] = 'https://www.' + ''.join(random.choices(string.ascii_letters, k=5)) + '.com'

            elif field.get_internal_type() == 'DateField':
                data[field.name] = datetime.now().date().isoformat()
            
            elif field.get_internal_type() == 'DecimalField':
                data[field.name] = random.uniform(1.0, 100.0)

            elif field.get_internal_type() == 'PositiveIntegerField':
                data[field.name] = random.randint(1, 100)

            elif field.get_internal_type() == 'ManyToManyField':
                continue  # Handle ManyToManyField after instance creation

        # Create the instance without saving

        instance = model(**data)
        
        return instance

    except Exception as e:
        print(f"An error occurred with field {field}: {e}")
        return None



