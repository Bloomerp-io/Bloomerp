# Bloomerp

Bloomerp is an open-source Django framework for building business management
applications from database models. It provides model-driven CRUD pages, data
views, workspaces, generated APIs, workflow automation, and an AI assistant,
with room for custom Django logic and frontend components.

The backend uses Django and Django REST Framework. The interface combines
HTMX, Django Cotton, Tailwind CSS, and TypeScript bundled with Vite. Django
Channels supports live updates, and Celery supports background work.

## Features

- **Model-driven applications**: Create, view, edit, and delete records, with
  configurable detail layouts, tabs, object actions, and activity logging.
- **Data views and search**: Filter and search records, use table, kanban, and
  calendar views, and find accessible data through global search.
- **Permissions**: Policies control model, row, and field access across the UI
  and generated APIs.
- **Workspaces**: Build dashboards with analytics, links, text, and Excalidraw
  canvas tiles, backed by reusable tile definitions and SQL queries.
- **Imports and APIs**: Bulk-import records and generate REST endpoints and
  Python, JavaScript, or TypeScript SDKs from model definitions.
- **Files and collaboration**: Organize files in folders, attach them to records,
  and use comments, mentions, and communication channels.
- **Documents**: Create document templates and generate documents from model data.
- **Workflow automation**: Build workflows from registered trigger, action, and
  flow nodes, with branching, execution logs, and extensible executors.
- **BloomAI**: Configure agents and providers for streaming conversations,
  tool use, approval requests, and file or module attachments. AI features
  require instance configuration and provider credentials.
- **Model Context Protocol (MCP)**: Expose registered tools and reference
  resources through an instance's `/mcp` endpoint under the caller's identity.
- **Project CLI**: Scaffold and synchronize Django projects and reusable apps,
  and build, link, and deploy projects through Bloomerp.io.

These capabilities are implemented in this repository. Availability in an
application depends on its configuration, enabled integrations, and user access.

## Getting started

### Install and create a project

Use Python 3.12 or 3.13 for generated projects. Start in an empty working
directory and install Bloomerp in a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install bloomerp
bloomerp project init mycrm --app sales --no-input
cd mycrm
pip install -e .
```

The activation command above is for macOS/Linux; on Windows, activate with
`.venv\Scripts\Activate.ps1` in PowerShell. If you use `uv`, install Bloomerp
with `uv add bloomerp` and invoke the CLI with `uv run bloomerp`.

`project init` creates a Django project, a `.bloomerp/project.bloomerp.toml`
manifest, and the `apps.sales` application. The generated settings include
Bloomerp's user model, middleware, and URL configuration. Local development
uses SQLite by default.

### Define a model

Create `apps/sales/models/customer.py`:

```python
from django.db import models

from bloomerp.models import BloomerpModel
from bloomerp.models.definition import BloomerpModelConfig, StringSearchSettings


class Customer(BloomerpModel):
    """Store customer contact details for the sales application."""

    bloomerp_config = BloomerpModelConfig(
        string_search_settings=StringSearchSettings(
            string_search_fields=["name", "email"],
        ),
    )

    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)

    def __str__(self) -> str:
        """Return the customer name for record labels."""
        return self.name
```

Import it in `apps/sales/models/__init__.py` so Django discovers it:

```python
from .customer import Customer
```

Create the schema and register the application's field metadata:

```bash
python manage.py makemigrations sales
python manage.py migrate
python manage.py save_application_fields
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/` and sign in with the superuser account. Run
`makemigrations`, `migrate`, and `save_application_fields` again when changing
model fields. Configure policies before granting other users access.

### Configure and extend the application

- Manage project declarations in `.bloomerp/project.bloomerp.toml` and dependencies
  in `pyproject.toml`.
- Put shared custom settings in `config/settings/common.py`, and local or
  production overrides in `config/settings/local.py` or
  `config/settings/production.py`.
- Add custom URLs in `config/project_urls.py` and websocket routes in
  `config/project_channels.py`.
- Use `BloomerpModelConfig` to configure model views, layouts, search, actions,
  activity logging, and API generation.
- Run `bloomerp project sync` to synchronize project scaffolding after upgrading
  Bloomerp or changing app declarations. Keep custom settings in project-owned
  files; files under `config/settings/generated/` are managed by the CLI.

Generated API access is configured through `ApiSettings.access` and
`ApiAccessSettings`, using unified `AccessRule` row and field grants for
anonymous or authenticated callers. API nesting controls response expansion;
permissions still govern access to related records and fields.

Background workflows and live features need their corresponding workers and
services in production. Configure production database, broker, channel layer,
file storage, and secrets for your deployment rather than relying on the local
SQLite and in-memory defaults.

## Documentation

The repository contains guides for extending the framework:

- [Router, views, components, and MCP tools](docs/developers/router/index.md)
- [Data views](docs/developers/dataviews/index.md)
- [Fields and lookups](docs/developers/fields/index.md)
- [Workspace tiles](docs/developers/workspaces/index.md)
- [Workflow nodes](docs/developers/automation/index.md)
- [MCP tools and resources](docs/developers/mcp/index.md)
- [BloomAI runtime and provider configuration](bloomerp/django_bloomerp/bloomerp/agents/README.md)
- [Django Cotton components](docs/developers/cotton/index.md)
- [Frontend development](bloomerp/django_bloomerp/bloomerp/static_src/README.md)
- [Testing and scenario frameworks](docs/developers/testing/index.md)

## Working on the framework

The Python package and development Django project live in
`bloomerp/django_bloomerp/`. Frontend source lives in its
`bloomerp/static_src/` directory; developer and user documentation lives in `docs/`.

Install the repository's Python dependencies from the package directory:

```bash
cd bloomerp/django_bloomerp
uv sync
```

Use the project's local settings for development. To initialize a local database
and start Django, run the same `migrate`, `save_application_fields`,
`createsuperuser`, and `runserver` commands above with `uv run`.

For frontend changes, use Node.js 22 (the version used by the package publishing
workflow) and npm:

```bash
cd bloomerp/static_src
npm install
npm run dev
```

Run the Django server in a separate terminal. `npm run build` produces the
production assets, and `npm run type-check` checks TypeScript without emitting
bundles. Published packages include compiled assets, so application developers
only need this toolchain when changing frontend source.

Read the [testing guide](docs/developers/testing/index.md) before adding tests.
Choose the narrowest layer that owns the behavior and use its established base
test case and scenario framework. From `bloomerp/django_bloomerp/`, run a focused
suite with:

```bash
uv run python manage.py test <test_module>
```

Replace `<test_module>` with the dotted path of the relevant test module. See
the [end-to-end guide](docs/developers/testing/e2e-test-case.md) for browser test
setup and execution.

## Contributing

Bug reports, feature requests, documentation improvements, and pull requests
are welcome. Open an issue with reproduction steps for a bug, or describe the
use case for a proposed feature. For a code change, create a branch, keep the
scope focused, and include the relevant verification results in your PR.

Project coding and testing conventions are recorded in [AGENTS.md](AGENTS.md).

## License

Bloomerp is licensed under the [GNU Affero General Public License v3](LICENSE.txt).
By contributing, you agree that your contributions will be licensed under the
AGPL v3 and may be used in commercially licensed versions of this software.

For commercial licensing options, contact
[bloomer.david@outlook.com](mailto:bloomer.david@outlook.com).
