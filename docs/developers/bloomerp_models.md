# Bloomerp Models

## Class BloomerpModel

The `BloomerpModel` class is the base model for all models in the Bloomerp framework. It provides a set of common functionalities and attributes that are essential for integrating with Bloomerp's features.

### Attributes

- **files**: A generic relation to the `File` model, allowing any Bloomerp model to have associated files.
- **comments**: A generic relation to the `Comment` model, enabling commenting functionality on any Bloomerp model.
- **string_search_fields**: Specifies fields for string-based searches. This attribute should be defined in the subclass.
- **allow_string_search**: A boolean that determines if the model is searchable via the global search bar. This attribute should be defined in the subclass.

### Mixins

The `BloomerpModel` class inherits from several mixins that provide additional functionalities:

- **TimestampModelMixin**: Adds `created_at` and `updated_at` fields to track the creation and modification times.
- **StringSearchModelMixin**: Provides methods for performing string-based searches on the specified fields.
- **UserStampModelMixin**: Adds `created_by` and `updated_by` fields to track the user who created and last modified the record.
- **AbsoluteUrlModelMixin**: Provides a method to get the absolute URL of the model instance.

### Meta Options

- **abstract**: Indicates that this is an abstract base class.
- **default_permissions**: Specifies the default permissions for the model, including custom permissions like `bulk_change`, `bulk_delete`, `bulk_add`, and `export`.

### Example Usage

Here is an example of how to define a model that inherits from `BloomerpModel`:

```python
from django.db import models
from bloomerp.models import BloomerpModel
from bloomerp.models.fields import BloomerpFileField
from django.utils import timezone

class Customer(BloomerpModel):
    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=15)
    address = models.TextField()

    string_search_fields = ['name', 'email']
    allow_string_search = True

class Product(BloomerpModel):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    image = BloomerpFileField(allowed_extensions=['.jpg', '.jpeg', '.png'])
    price = models.DecimalField(max_digits=10, decimal_places=2)

    string_search_fields = ['name', 'description']
    allow_string_search = True

class Order(BloomerpModel):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    )
    date = models.DateField(default=timezone.now)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField()
    status = models.CharField(max_length=255, choices=STATUS_CHOICES, default='pending')

    string_search_fields = ['product__name', 'status']
    allow_string_search = True
```

In this example, `Customer`, `Product`, and `Order` models inherit from `BloomerpModel`, gaining all the functionalities provided by the base class and its mixins. The `string_search_fields` and `allow_string_search` attributes are defined to enable string-based searches on specific fields.

## Class File

The `File` class represents a file within the Bloomerp framework. It includes metadata and references to the content it is associated with.

### Fields

- **id**: A UUID that uniquely identifies the file.
- **file**: The file itself, stored using Django's `FileField`.
- **name**: The name of the file.
- **content_type**: A ForeignKey to Django's `ContentType` model, representing the type of content the file is related to.
- **object_id**: The ID of the related object.
- **content_object**: A `GenericForeignKey` linking to the related object.
- **persisted**: A boolean indicating if the file is temporary or persisted.
- **meta**: A JSONField storing additional metadata about the file.

### Properties

- **url**: Returns the URL of the file.
- **file_extension**: Returns the file extension.
- **size**: Returns the size of the file in bytes.
- **size_str**: Returns the size of the file in a human-readable format.

### Methods

- **get_accessible_files(query, user, folder=None, content_type=None, object_id=None)**: Returns a queryset of accessible files based on the provided parameters.

### Example Usage

```python
from bloomerp.models.core import File

# Creating a new file
new_file = File.objects.create(
    file='path/to/file.pdf',
    name='Sample File',
    content_type=ContentType.objects.get_for_model(SomeModel),
    object_id=1,
    persisted=True
)

# Accessing file properties
print(new_file.url)
print(new_file.size_str)

# Deleting a file
new_file.delete()

## Get all accessible files for a particular user


```

In this example, a `File` instance is created, its properties are accessed, and it is later deleted. The `get_accessible_files` method can be used to retrieve files accessible to a particular user based on various filters.

