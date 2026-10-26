# __APP_LABEL__ frontend

Run `npm install` then `npm run build` here. Commit package-lock.json for repeatable
builds. Bloomerp app wheel builds also build this workspace before packaging its
static assets; Node.js is only required on the build machine.

The `@bloomerp/frontend` dependency comes from the installed Python framework,
through the generated `.bloomerp/frontend-api` directory. It is not downloaded
from npm. After a fresh checkout or framework upgrade, run
`bloomerp app frontend __APP_LABEL__ --sync-api` from the project before npm install.
App wheel builds refresh this copy automatically. Do not edit the generated API.

Use `<div bloomerp-component="__APP_LABEL__:example"></div>` in an app template.
The static frontend.json descriptor lets Bloomerp discover this bundle when the
Django app is installed. Keep its static namespace in sync if you change AppConfig.label.

For live development, run `npm run dev` here and add this to local Django settings:

```python
BLOOMERP_VITE_DEV_SERVER_URL = ""
BLOOMERP_FRONTEND_DEV_SERVERS = {"__APP_LABEL__": "http://localhost:5174"}
```

The first setting uses core assets bundled with Bloomerp; the second enables live
development only for this app. To edit framework TypeScript too, run core's Vite
server separately and set BLOOMERP_VITE_DEV_SERVER_URL to its URL (normally port
5173). That core URL can also come from BLOOMERP_CONFIG.vite_dev_server_url when
there is no explicit Django override. Use a distinct port per app server.

Keep @bloomerp/frontend external in Vite so the browser uses core's shared registry.
Add dependencies to this workspace, and import CSS here. If using Tailwind, configure this app's own
CSS compilation to scan its templates and TypeScript. Avoid adding another CSS reset.
