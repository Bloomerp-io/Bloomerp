# Developer documentation

Use these guides when building a Django application with Bloomerp or extending
the framework. Commands in the guides run from your generated project directory
(the directory containing `manage.py`) unless a repository path is specified.

## Build an application

1. [Create a project](getting-started.md), add a model, and start the server.
2. [Configure models and modules](models/index.md): layouts, search, generated
   APIs, and access rules.
3. [Add routes](router/index.md) for custom pages and component endpoints.
4. [Configure authentication](authentication.md) for browser and API clients.
5. [Generate tests](testing/index.md) and add scenarios for your application's
   behavior.

## Extend a feature

| Task | Guide |
| --- | --- |
| Render collections or add toolbar actions | [Dataviews](dataviews/index.md), [actions](dataviews/actions.md) |
| Configure boards or calendars | [Kanban](dataviews/kanban.md), [calendar](dataviews/calendar.md) |
| Build dashboards from reusable tiles | [Workspaces](workspaces/index.md) |
| Add field types, lookups, or filter controls | [Fields and filters](fields/index.md) |
| Store files or extract their contents | [File fields](fields/file-field.md), [file extraction](file-extraction.md) |
| Use template UI components | [Cotton component reference](cotton/index.md) |
| Add a workflow node | [Automation](automation/index.md) |
| Expose tools and reference material to AI clients | [MCP](mcp/index.md) |
| Integrate phone conversations | [VoIP](voip.md) |
| Publish mention notifications | [Mention notifications](mention-notifications.md) |

The [testing index](testing/index.md) maps each extension to its generated base
test case. Prefer the smallest layer that verifies the behavior being changed.
