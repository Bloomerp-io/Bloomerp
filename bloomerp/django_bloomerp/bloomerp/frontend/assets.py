"""Resolve implementation frontend entries through Django static storage."""

import json
import posixpath
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from django.apps import apps
from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.exceptions import ImproperlyConfigured
from django.templatetags.static import static


def read_json_object(path: Path) -> dict[str, Any]:
    """Read an asset descriptor or manifest and report actionable errors."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("Expected a JSON object")
        return data
    except (OSError, ValueError, TypeError) as error:
        raise ImproperlyConfigured(
            f"Invalid frontend asset configuration: {path}"
        ) from error


def static_asset_path(prefix: str, filename: str) -> str:
    """Resolve a manifest filename while keeping assets inside its namespace."""
    path = PurePosixPath(filename)
    if (
        not filename
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in filename
        or urlsplit(filename).scheme
    ):
        raise ImproperlyConfigured(f"Invalid frontend asset path: {filename!r}")
    return posixpath.join(prefix, filename)


def resolve_bundle(manifest_name: str, entry_name: str) -> dict[str, Any]:
    """Return an entry URL and all CSS required by its static import graph."""
    manifest_path = finders.find(manifest_name)
    if not manifest_path:
        raise ImproperlyConfigured(
            f"Missing frontend manifest {manifest_name}. Run npm install and npm run build in the app's frontend directory."
        )
    manifest = read_json_object(Path(manifest_path))
    prefix = posixpath.dirname(manifest_name)
    styles: list[str] = []
    visited: set[str] = set()

    def visit(key: str) -> None:
        """Collect dependency styles once, before the importing entry's styles."""
        if key in visited:
            return
        visited.add(key)
        chunk = manifest[key]
        for dependency in chunk.get("imports", []):
            visit(dependency)
        for filename in chunk.get("css", []):
            url = static(static_asset_path(prefix, filename))
            if url not in styles:
                styles.append(url)

    try:
        entry = manifest[entry_name]
        if not entry.get("isEntry"):
            raise ValueError("Manifest record is not an entry")
        script = static(static_asset_path(prefix, entry["file"]))
        visit(entry_name)
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise ImproperlyConfigured(
            f"Invalid frontend entry {entry_name!r} in {manifest_name}"
        ) from error
    return {"script": script, "styles": styles}


def get_frontend_assets() -> dict[str, Any]:
    """Discover installed app bundles and map their public API to core's runtime."""
    extensions: list[dict[str, Any]] = []
    dev_servers = (
        getattr(settings, "BLOOMERP_FRONTEND_DEV_SERVERS", {}) if settings.DEBUG else {}
    )
    for app in apps.get_app_configs():
        descriptor = Path(app.path) / "static" / app.label / "frontend.json"
        if not descriptor.is_file():
            continue
        config = read_json_object(descriptor)
        entry_name = config.get("entry", "ts/main.ts")
        dev_server = dev_servers.get(app.label)
        if dev_server:
            origin = dev_server.rstrip("/")
            if urlsplit(origin).scheme not in {"http", "https"}:
                raise ImproperlyConfigured(
                    f"Invalid frontend development server for {app.label}"
                )
            extensions.append(
                {
                    "script": f"{origin}/{entry_name}",
                    "styles": [],
                    "client": f"{origin}/@vite/client",
                }
            )
        else:
            manifest_name = config.get(
                "manifest", f"{app.label}/frontend/manifest.json"
            )
            extensions.append(resolve_bundle(manifest_name, entry_name))

    if not extensions:
        return {"imports": {}, "extensions": []}

    core_config = getattr(settings, "BLOOMERP_CONFIG", None)
    core_dev_server = getattr(
        core_config, "vite_dev_server_url", "http://localhost:5173"
    )
    if settings.DEBUG and core_dev_server:
        runtime = f"{core_dev_server.rstrip('/')}/ts/frontend.ts"
    else:
        runtime = resolve_bundle("bloomerp/js/dist/manifest.json", "ts/frontend.ts")[
            "script"
        ]
    return {
        "imports": {"@bloomerp/frontend": runtime, "@bloomerp/runtime": runtime},
        "extensions": extensions,
    }
