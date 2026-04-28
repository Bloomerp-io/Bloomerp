# Bloomerp

Bloomerp is an open-source Business Management Software framework that lets you create fully functional business management applications just by defining your Django database models.

It's out-of-the-box functionality gives you the ability to create advanced apps in minutes whilst maintaining the ability to add custom functionality without too much effort.

At its core, it leverages the popular Python framework Django and HTMX to provide robust and fast applications.

## Key features

Bloomerp comes packed with a variety of features:

- **Intuitive CRUD Views**: With integrated access control provided by Django.
- **Advanced List Views**: Offering powerful filtering capabilities and different view options (table, kanban, calendar, etc.).
- **Search Functionality**: A global, permission-aware search bar that allows you to search across all your data, giving you access to various parts of the application with immense speed.
- **Advanced permission system**: Granular yet intuitive control over who can see and do what within your application, by leveraging an RBAC system that goes beyond Django's or even Guardian's capabilities.
- **Customizable Workspaces**: Create intuitive workspaces that contain a variety of different tiles
    - **Analytics Tiles**: Display key metrics and insights from your data.
    - **Link Tiles**: Quick access to important views or external resources.
    - **Text Tiles**: For important notes or instructions.
    - **Canvas Tiles**: A flexible space where you can use Excalidraw to create diagrams, flowcharts, and more.
- **Bulk Uploads**: For efficiently importing data into models.
- **REST APIs**: Automatically generated permission-aware APIs for all your models, with the ability to customize public access and user access that go beyond the already impresive permission system provided by Bloomerp.
- **SDK Support**: Generate SDKs based on your model structure. Support for Python, JavaScript, and Typescript.
- **File System UI**: An intuitive interface including folder structures.
- **Commenting System**: Allows you to comment on specific objects.

## Getting Started

### Install Bloomerp

Download Bloomerp via pip

```sh
pip install bloomerp
```

or via uv (if you haven't tried uv yet, you're missing out!)

```sh
uv add bloomerp
```

Bloomerp has a dependency on Django and other libraries that will be automatically installed when you install Bloomerp.

### Setting up the project

Once you have Bloomerp installed, you can create a new project by running the command below. Note that you can also add Bloomerp to an existing Django project, but this requires you to do some manual tweaking with the settings, etc. So for the sake of simplicity, we'll start with a fresh project and will be using Bloomerp's cli tool to generate the necessary files and folders.

For this tutorial, let's create a small CRM application to manage customers, products, and orders.

```sh
bloomerp startproject mycrm
```

### Create Your Models

Let's define some basic models for our sales application: `Customer`, `Product`, and `Order`.

```python
from django.db import models
from bloomerp.models import BloomerpModel
from bloomerp.models.fields import BloomerpFileField
from django.utils import timezone
from bloomerp.models.definition import (
    BloomerpModelConfig,
    ApiSettings
)
from bloomerp.field_types import Lookup

class Customer(BloomerpModel):
    bloomerp_config = BloomerpModelConfig() # No particular configuration needed for this model

    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=15)
    address = models.TextField()


class Product(BloomerpModel):

    # We wanna set up the API settings so that the e-commerce frontend can easily retrieve product information without needing to log in. We also want to make sure that only active products are retrieved via the API, so we add a filter for that.

    bloomerp_config = BloomerpModelConfig(
        api_settings=ApiSettings(
            enable_auto_generation=True,  # Automatically generate API endpoints for this model
            public_access=[
                PublicAccessRule(
                    row_actions=['list', 'retrieve'] # Allow public to list and retrieve products
                    field_actions={
                        "name": ["list", "retrieve"],
                        "description": ["list", "retrieve"],
                        "image": ["list", "retrieve"],
                        "price": ["list", "retrieve"],
                    },
                    filters=[
                        ApiFilter(
                            ApiFilterRule(
                                field="active",
                                operator=Lookup.EQUALS.value.id,
                                value=True
                            )
                        )
                    ]
                )
            ]
        )
    )

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    image = BloomerpFileField(allowed_extensions=['.jpg', '.jpeg', '.png'])
    price = models.DecimalField(max_digits=10, decimal_places=2)
    active = models.BooleanField(default=True)

    

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
```

**Notes:**

1. **Inherit from `BloomerpModel`**: This ensures compatibility with Bloomerp's features.


Make migrations for your new models:

```sh
python manage.py makemigrations sales
python manage.py migrate sales
```

Add the endpoints in your `urls.py` file.
```python
# urls.py
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("bloomerp.urls")),  # Include Bloomerp's URLs
]
```


Every time you update your models, run:

```sh
python manage.py save_application_fields
```

Create a superuser to log in:

```sh
python manage.py createsuperuser
```

Start the server:

```sh
python manage.py runserver
```

## Found Errors? 🛑

If you encounter any bugs or issues, please let us know:

- **Open an Issue**: Report it on our GitHub issues page with details about the problem.
- **Contact Us**: Reach out directly via email or our community channels.

Your feedback helps us improve Bloomerp for everyone!

## Roadmap 🧭

We're currently at **version 1.0.0**, and we have big plans for the future. Here's what's coming up:

- **Reintroduction of BloomAI**: The previous AI assistant feature will be reintroduced with enhanced capabilities, including better natural language understanding and more powerful automation features.
- **Workflow Automation**: We're planning to add a workflow automation engine that will allow users to create custom workflows and automate repetitive tasks across their applications.
- **More Tile Types**: We will be adding more types of tiles for the customizable workspaces, such as calendar tiles, task list tiles, and more.
- **More**: We have a lot of other features in the pipeline, and we're always open to suggestions from the community on what to prioritize next.


Stay tuned for updates, and feel free to contribute to any of these upcoming features!

## Want to Contribute? 🤝

Each time I've referred to 'we' throughout this document, I'm actually only refering to myself (gotta stay professional). However I would love your help in making Bloomerp a **WE** project in the future 😉 ! Whether it's fixing bugs, adding new features, or improving documentation, your contributions are more than welcome.

- **Fork the Repository**: Start by forking the Bloomerp repository on GitHub.
- **Create a Branch**: Make a new branch for your feature or bug fix.
- **Submit a Pull Request**: When you're ready, submit a pull request for review.

Feel free to open issues for feature requests or discussions.


## License
By contributing to this project, you agree that your contributions will be licensed under the AGPL v3 and may be used in commercially licensed versions of this software.

This project is licensed under the [GNU Affero General Public License v3](LICENSE.txt).

For commercial licensing options, please contact [bloomer.david@outlook.com](mailto:bloomer.david@outlook.com).
