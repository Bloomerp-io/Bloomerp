# Bloomerp

Bloomerp is a Django framework for business applications with model-driven
pages, dataviews, workspaces, generated APIs, workflow automation, and MCP tools.

Use Python 3.12 or 3.13 for generated projects. In an activated virtual environment:

```sh
pip install bloomerp
bloomerp project init mycrm --app sales --no-input
cd mycrm
pip install -e .
python manage.py migrate
python manage.py save_application_fields
python manage.py createsuperuser
python manage.py runserver
```

Continue with the [developer documentation](https://github.com/Bloomerp-io/Bloomerp/blob/main/docs/developers/index.md)
for model configuration, authentication, extensions, and testing. The
[getting-started guide](https://github.com/Bloomerp-io/Bloomerp/blob/main/docs/developers/getting-started.md)
shows how to add your first model.

Bloomerp is licensed under the GNU Affero General Public License v3. See the
[repository](https://github.com/Bloomerp-io/Bloomerp) for source and licensing details.
