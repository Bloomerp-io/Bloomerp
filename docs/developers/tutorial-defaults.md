# Ship default tutorials

Place YAML files in a `tutorials/` directory inside your installed Django app's
package and include them as package data. Run these commands from the project
directory after deploying the app.

```sh
python manage.py migrate
python manage.py save_application_fields
python manage.py sync_defaults tutorials
```

`sync_defaults` without a domain also synchronizes tutorials. The application
field metadata is used to validate audience filters and to authorize exports.

Each tutorial file uses the same versioned format as **Export YAML** in the
Tutorials toolbar. Give an export a stable `source_key` before shipping it.
Keys are slugs containing lowercase letters and digits, with optional
hyphen or underscore separators. The synchronizer scopes them to the owning
app's Python package name. For example, `welcome` in `example.onboarding`
is stored as `example.onboarding:welcome`. A filename or display name can
change independently of the key.

```yaml
schema_version: 1
tutorial:
  source_key: welcome
  name: Welcome
  available_to_all: true
  topics: [getting-started]
  revisions:
    - number: 1
      published_at: "2026-11-23T00:00:00+00:00"
      trigger_route: bloomerp_home_view
      auto_start: false
      steps:
        - sequence: 1
          key: home
          name: Your home page
          text: Use the sidebar to open a module.
```

Define shared topics in a manifest such as `tutorials/topics.yaml`.
Tutorials can also reference another installed app's topic by its qualified key.

```yaml
schema_version: 1
topics:
  - source_key: getting-started
    name: Getting started
    description: Learn the basics.
    sequence: 10
```

An initial install uses the declared `is_active`, `available_to_all`, and
`user_filter` defaults. Later syncs preserve instance changes to those
settings and preserve direct user and group assignments. A filter narrows the
assigned audience. It does not grant access by itself. Use filter values that
make sense across the instances that will install the tutorial.

Publish edited content under a new revision number. Reusing an existing
number is safe when the step content and revision settings match. Sync
preserves previous revisions and learner progress. To retire a tutorial,
replace its definition with an explicit retirement declaration.

```yaml
schema_version: 1
retire: welcome
```

Removing a file leaves the saved tutorial available. Replacing the retirement
declaration with a tutorial definition restores the same identity and history.
