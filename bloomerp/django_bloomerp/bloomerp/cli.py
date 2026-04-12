from __future__ import annotations

import keyword
import re
from pathlib import Path

import click


def _slugify_package_name(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    if not slug:
        raise click.ClickException("Project names must contain at least one letter or number.")
    if slug[0].isdigit():
        slug = f"project_{slug}"
    if keyword.iskeyword(slug):
        slug = f"{slug}_project"
    return slug


def _display_name(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").strip().title()


def _distribution_name(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9-]+", "-", value).strip("-").lower()
    if not slug:
        raise click.ClickException("Project names must contain at least one letter or number.")
    return slug


def _write_file(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def _manage_py(settings_module: str) -> str:
    return f"""#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "{settings_module}")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
"""


def _settings_py(project_package: str, app_name: str, organization_name: str) -> str:
    return f"""from pathlib import Path

from bloomerp.config import BLOOMERP_APPS, BLOOMERP_MIDDLEWARE, BLOOMERP_USER_MODEL

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "change-me"
DEBUG = True
ALLOWED_HOSTS = []

LOGIN_URL = "/login"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "{app_name}",
]
INSTALLED_APPS += BLOOMERP_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
MIDDLEWARE += BLOOMERP_MIDDLEWARE

ROOT_URLCONF = "{project_package}.urls"

TEMPLATES = [
    {{
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {{
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        }},
    }},
]

WSGI_APPLICATION = "{project_package}.wsgi.application"
ASGI_APPLICATION = "{project_package}.asgi.application"

DATABASES = {{
    "default": {{
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }}
}}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = BLOOMERP_USER_MODEL

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

BLOOMERP_SETTINGS = {{
    "globals": {{
        "organization_name": "{organization_name}",
    }},
    "BASE_URL": "",
    "ROUTERS": [],
}}
"""


def _urls_py() -> str:
    return """from django.contrib import admin
from django.urls import path

from bloomerp.urls import BLOOMERP_URLPATTERNS

urlpatterns = [
    path("admin/", admin.site.urls),
    BLOOMERP_URLPATTERNS,
]
"""


def _wsgi_py(project_package: str) -> str:
    return f"""import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "{project_package}.settings")

application = get_wsgi_application()
"""


def _asgi_py(project_package: str) -> str:
    return f"""import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "{project_package}.settings")

application = get_asgi_application()
"""


def _app_config_py(app_name: str, app_class_name: str) -> str:
    return f"""from django.apps import AppConfig


class {app_class_name}(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "{app_name}"
"""


def _models_py() -> str:
    return """from django.db import models

from bloomerp.models import BloomerpModel


class ExampleRecord(BloomerpModel):
    name = models.CharField(max_length=255)

    string_search_fields = ["name"]
    allow_string_search = True

    def __str__(self) -> str:
        return self.name
"""


def _admin_py(app_name: str) -> str:
    return f"""from django.contrib import admin

from {app_name}.models import ExampleRecord


admin.site.register(ExampleRecord)
"""


def _generated_pyproject(distribution_name: str) -> str:
    return f"""[project]
name = "{distribution_name}"
version = "0.1.0"
description = "Bloomerp starter project"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "Django>=5.1,<6.0",
    "Bloomerp>=0.1.0",
]

[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"
"""


def _readme(project_name: str) -> str:
    return f"""# {project_name}

This project was created with `bloomerp init`.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python manage.py migrate
python manage.py createsuperuser
python manage.py save_application_fields
python manage.py runserver
```
"""


def _gitignore() -> str:
    return """.venv/
__pycache__/
*.pyc
db.sqlite3
staticfiles/
"""


@click.group()
def main() -> None:
    """Bloomerp command line tools."""


@main.command()
@click.argument("directory", required=False)
def init(directory: str | None) -> None:
    """Create a new Django project configured for Bloomerp."""

    target_name = directory or click.prompt("Project directory", default="my-bloomerp-project")
    target_dir = Path(target_name).expanduser().resolve()

    default_project_name = target_dir.name
    project_name = click.prompt("Project name", default=default_project_name)
    project_package = click.prompt(
        "Python package name",
        default=_slugify_package_name(project_name),
        show_default=True,
    )
    app_name = click.prompt("Main Django app", default="core", show_default=True)
    app_name = _slugify_package_name(app_name)
    organization_name = click.prompt(
        "Organization name",
        default=_display_name(project_name),
        show_default=True,
    )
    distribution_name = _distribution_name(project_name)

    if target_dir.exists() and any(target_dir.iterdir()):
        raise click.ClickException(f"Target directory already exists and is not empty: {target_dir}")

    app_class_name = "".join(part.capitalize() for part in app_name.split("_")) + "Config"
    settings_module = f"{project_package}.settings"

    files = {
        target_dir / "manage.py": _manage_py(settings_module),
        target_dir / "pyproject.toml": _generated_pyproject(distribution_name),
        target_dir / "README.md": _readme(project_name),
        target_dir / ".gitignore": _gitignore(),
        target_dir / project_package / "__init__.py": "",
        target_dir / project_package / "settings.py": _settings_py(project_package, app_name, organization_name),
        target_dir / project_package / "urls.py": _urls_py(),
        target_dir / project_package / "wsgi.py": _wsgi_py(project_package),
        target_dir / project_package / "asgi.py": _asgi_py(project_package),
        target_dir / app_name / "__init__.py": "",
        target_dir / app_name / "apps.py": _app_config_py(app_name, app_class_name),
        target_dir / app_name / "models.py": _models_py(),
        target_dir / app_name / "admin.py": _admin_py(app_name),
        target_dir / app_name / "migrations" / "__init__.py": "",
    }

    for path, contents in files.items():
        _write_file(path, contents)

    click.echo(f"Created Bloomerp project at {target_dir}")
    click.echo("")
    click.echo("Next steps:")
    click.echo(f"  cd {target_dir}")
    click.echo("  python -m venv .venv")
    click.echo("  source .venv/bin/activate")
    click.echo("  pip install -e .")
    click.echo("  python manage.py migrate")
    click.echo("  python manage.py createsuperuser")
    click.echo("  python manage.py save_application_fields")
    click.echo("  python manage.py runserver")


if __name__ == "__main__":
    main()
