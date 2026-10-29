# Create a Bloomerp application

Use Python 3.12 or 3.13 for generated projects. From an empty working directory:

```sh
python -m venv .venv
source .venv/bin/activate
pip install bloomerp
bloomerp project init mycrm --app sales --no-input
cd mycrm
pip install -e .
```

On Windows, activate the environment with `.venv\Scripts\Activate.ps1` in
PowerShell. The generated project includes SQLite development settings,
Bloomerp's user model, middleware, and URLs, plus the `apps.sales` application.
Do not add a second `include("bloomerp.urls")` to the generated URL configuration.

## Add a model

Create `apps/sales/modules.py` to declare the module that owns the sales pages:

```python
from bloomerp.modules.definition import BloomerpModule


class SalesModule(BloomerpModule):
    """Group sales models and their generated pages."""

    id = "sales"
    name = "Sales"
```

Create `apps/sales/models/customer.py`:

```python
from django.db import models

from bloomerp.models import BloomerpModel
from bloomerp.models.definition import BloomerpModelConfig, StringSearchSettings


class Customer(BloomerpModel):
    """Store contact details for a sales customer."""

    bloomerp_config = BloomerpModelConfig(
        module="sales",
        string_search_settings=StringSearchSettings(
            string_search_fields=["name", "email"],
        ),
    )

    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)

    def __str__(self) -> str:
        """Return the customer label used in record selectors and links."""
        return self.name
```

Import the model in `apps/sales/models/__init__.py` so Django discovers it:

```python
from .customer import Customer
```

Keep each model in its own file. See [model configuration](models/index.md) for
layouts, collection views, access rules, and generated APIs.

## Create the database and run

```sh
python manage.py makemigrations sales
python manage.py migrate
python manage.py save_application_fields
python manage.py createsuperuser
python manage.py runserver
```

Open the local server and sign in with the superuser. Ordinary users need the
appropriate model, row, and field permissions. A model's `__str__` value is its
public label for users who can access that object; avoid putting sensitive
field values in it.

Run `save_application_fields` after changing model fields. It synchronizes the
metadata used by filtering, permissions, forms, and dataviews; it does not replace
Django migrations.

## Where changes belong

| Change | Location |
| --- | --- |
| Dependencies | `pyproject.toml` |
| Registered apps and project configuration | `.bloomerp/project.bloomerp.toml` |
| Shared Django setting overrides | `config/settings/common.py` |
| Local or production overrides | `config/settings/local.py` or `production.py` |
| Custom URL includes | `config/project_urls.py` |
| Models and routed views | `apps/<app>/models/` and `apps/<app>/views/` |

Run `bloomerp project sync` after upgrading Bloomerp. It can replace files under
`config/settings/generated/`; put your overrides in the project-owned files
listed above. Use `bloomerp project --help` and `bloomerp app --help` for the CLI
commands shipped with your installed version.

Next, [generate test cases](testing/index.md) for `sales` and add scenarios for
its behavior.
