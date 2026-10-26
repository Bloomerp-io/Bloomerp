# __APP_LABEL__ frontend

Run `npm install` then `npm run build` here. Commit package-lock.json for repeatable
builds. Bloomerp app wheel builds also build this workspace before packaging its
static assets; Node.js is only required on the build machine.

Use `<div bloomerp-component="__APP_LABEL__:example"></div>` in an app template.
The static frontend.json descriptor lets Bloomerp discover this bundle when the
Django app is installed. Keep its static namespace in sync if you change AppConfig.label.

For live development, run `npm run dev` here and add this to local Django settings:

```python
BLOOMERP_FRONTEND_DEV_SERVERS = {"__APP_LABEL__": "http://localhost:5174"}
```

Run core's development server on port 5173, or disable core's Vite server in
BLOOMERP_CONFIG to use built core assets. Use a distinct port per app server.

Keep @bloomerp/frontend external in Vite so the browser uses core's shared registry.
Use the npm package version matching the deployed Python framework. Add dependencies
to this workspace, and import CSS here. If using Tailwind, configure this app's own
CSS compilation to scan its templates and TypeScript. Avoid adding another CSS reset.
