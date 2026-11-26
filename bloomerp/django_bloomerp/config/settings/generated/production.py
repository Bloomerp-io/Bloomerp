import os
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(
            f"Missing required environment variable: {name}"
        )
    return value


def required_environment_list(name: str) -> list[str]:
    return [
        value.strip()
        for value in required_environment(name).split(",")
        if value.strip()
    ]


SECRET_KEY = required_environment("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = required_environment_list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = required_environment_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS"
)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": required_environment("POSTGRES_DB"),
        "USER": required_environment("POSTGRES_USER"),
        "PASSWORD": required_environment("POSTGRES_PASSWORD"),
        "HOST": required_environment("POSTGRES_HOST"),
        "PORT": required_environment("POSTGRES_PORT"),
    }
}

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.environ.get(
    "CELERY_RESULT_BACKEND",
    "redis://redis:6379/1",
)
CHANNEL_LAYERS_REDIS_URL = os.environ.get(
    "CHANNEL_LAYERS_REDIS_URL",
    "redis://redis:6379/2",
)
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [CHANNEL_LAYERS_REDIS_URL]},
    }
}



CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "request_tokens": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("REQUEST_TOKEN_REDIS_URL", CHANNEL_LAYERS_REDIS_URL),
    },
}

def boolean_environment(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


OBJECT_STORAGE_ENABLED = boolean_environment("OBJECT_STORAGE_ENABLED", False)
if OBJECT_STORAGE_ENABLED:
    object_storage_endpoint = required_environment("OBJECT_STORAGE_ENDPOINT_URL")
    object_storage_bucket = required_environment("OBJECT_STORAGE_BUCKET_NAME")
    object_storage_access_key = required_environment(
        "OBJECT_STORAGE_ACCESS_KEY_ID"
    )
    object_storage_secret_key = required_environment(
        "OBJECT_STORAGE_SECRET_ACCESS_KEY"
    )
    object_storage_use_ssl = boolean_environment("OBJECT_STORAGE_USE_SSL", True)
    object_storage_querystring_auth = boolean_environment(
        "OBJECT_STORAGE_QUERYSTRING_AUTH",
        False,
    )
    object_storage_media_prefix = os.environ.get(
        "OBJECT_STORAGE_MEDIA_PREFIX",
        "media",
    ).strip("/")
    object_storage_addressing_style = os.environ.get(
        "OBJECT_STORAGE_ADDRESSING_STYLE",
        "path",
    ).strip().lower() or "path"
    object_storage_region = os.environ.get("OBJECT_STORAGE_REGION", "").strip()
    object_storage_public_base_url = os.environ.get(
        "OBJECT_STORAGE_PUBLIC_BASE_URL",
        "",
    ).strip()

    storage_options = {
        "bucket_name": object_storage_bucket,
        "endpoint_url": object_storage_endpoint,
        "access_key": object_storage_access_key,
        "secret_key": object_storage_secret_key,
        "default_acl": None,
        "file_overwrite": False,
        "querystring_auth": object_storage_querystring_auth,
        "location": object_storage_media_prefix,
        "addressing_style": object_storage_addressing_style,
        "use_ssl": object_storage_use_ssl,
    }
    if object_storage_region:
        storage_options["region_name"] = object_storage_region
    if object_storage_public_base_url:
        parsed_public_url = urlparse(object_storage_public_base_url)
        public_base_path = parsed_public_url.path.rstrip("/")
        custom_domain = parsed_public_url.netloc
        if public_base_path:
            custom_domain = f"{custom_domain}{public_base_path}"
        storage_options["custom_domain"] = custom_domain
        storage_options["url_protocol"] = (
            f"{parsed_public_url.scheme or ('https' if object_storage_use_ssl else 'http')}:"
        )

    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": storage_options,
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
    if object_storage_public_base_url:
        MEDIA_URL = (
            f"{object_storage_public_base_url.rstrip('/')}/"
            f"{object_storage_media_prefix}/"
        )

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "true").lower() == "true"
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
