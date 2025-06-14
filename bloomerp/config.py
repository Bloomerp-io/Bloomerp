BLOOMERP_APPS = [
    "bloomerp",
    "django_htmx",
    "crispy_forms",
    "crispy_bootstrap5",
    "rest_framework",
    "django_filters",
    "tailwind",
    "django_cotton"
]

BLOOMERP_MIDDLEWARE = [
    "bloomerp.middleware.HTMXPermissionDeniedMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django_browser_reload.middleware.BrowserReloadMiddleware",
]

BLOOMERP_USER_MODEL = "bloomerp.User"

