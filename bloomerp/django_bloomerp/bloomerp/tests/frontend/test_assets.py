"""Verify asset discovery, shared runtime URLs, CSS dependencies, and development mode."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.template.loader import render_to_string
from django.test import override_settings

from bloomerp.frontend.assets import (
    get_frontend_assets,
    resolve_bundle,
    static_asset_path,
)
from bloomerp.templatetags.bloomerp_frontend import frontend_importmap


def write_json(path: Path, data: dict) -> None:
    """Write a fixture manifest or discovery descriptor."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_bundle_loads_dependency_css_once(tmp_path: Path) -> None:
    """Resolve entry and dependency styles through the deployment's static URL."""
    manifest = tmp_path / "manifest.json"
    write_json(
        manifest,
        {
            "ts/main.ts": {
                "isEntry": True,
                "file": "main-a.js",
                "imports": ["_shared"],
                "css": ["main-a.css", "shared.css"],
            },
            "_shared": {"file": "shared.js", "css": ["shared.css"]},
        },
    )
    with (
        override_settings(STATIC_URL="https://cdn.example.com/static/"),
        patch("bloomerp.frontend.assets.finders.find", return_value=str(manifest)),
    ):
        bundle = resolve_bundle("planner/frontend/manifest.json", "ts/main.ts")
    assert bundle == {
        "script": "https://cdn.example.com/static/planner/frontend/main-a.js",
        "styles": [
            "https://cdn.example.com/static/planner/frontend/shared.css",
            "https://cdn.example.com/static/planner/frontend/main-a.css",
        ],
    }


@pytest.mark.parametrize(
    "filename",
    [
        "../escape.js",
        "/absolute.js",
        "https://example.com/code.js",
        "..\\escape.js",
        "",
    ],
)
def test_manifest_assets_stay_in_their_namespace(filename: str) -> None:
    """Reject filenames that escape the static namespace or become remote imports."""
    with pytest.raises(ImproperlyConfigured):
        static_asset_path("planner/frontend", filename)


def test_missing_build_has_actionable_error() -> None:
    """Discovering an unbuilt app reports the required frontend build command."""
    with (
        patch("bloomerp.frontend.assets.finders.find", return_value=None),
        pytest.raises(ImproperlyConfigured, match="npm run build"),
    ):
        resolve_bundle("planner/frontend/manifest.json", "ts/main.ts")


@pytest.mark.parametrize("development", [False, True])
def test_installed_app_uses_the_shared_core_runtime(
    tmp_path: Path, development: bool
) -> None:
    """Map extension imports to the same core API in production and development."""
    write_json(tmp_path / "static/planner/frontend.json", {})
    app = SimpleNamespace(label="planner", path=str(tmp_path))
    app_manifest = tmp_path / "app-manifest.json"
    core_manifest = tmp_path / "core-manifest.json"
    write_json(app_manifest, {"ts/main.ts": {"isEntry": True, "file": "planner-a.js"}})
    write_json(
        core_manifest,
        {
            "ts/frontend.ts": {"isEntry": True, "file": "frontend-a.js"},
            "ts/entry.ts": {"isEntry": True, "file": "main-a.js"},
        },
    )

    def find_manifest(name: str) -> str:
        """Resolve fixture manifests using the same namespaces as Django finders."""
        return str(core_manifest if name.startswith("bloomerp/") else app_manifest)

    with (
        override_settings(
            DEBUG=development,
            STATIC_URL="/static/",
            BLOOMERP_CONFIG=SimpleNamespace(
                vite_dev_server_url="http://localhost:5173"
            ),
            BLOOMERP_FRONTEND_DEV_SERVERS={"planner": "http://localhost:5174"},
        ),
        patch(
            "bloomerp.frontend.assets.apps", **{"get_app_configs.return_value": [app]}
        ),
        patch("bloomerp.frontend.assets.finders.find", side_effect=find_manifest),
    ):
        assets = get_frontend_assets()
        rendered = render_to_string(
            "snippets/vite_bundle.html",
            {
                "DEBUG": development,
                "BLOOMERP_VITE_DEV_SERVER_URL": "http://localhost:5173",
            },
        )
    runtime = (
        "http://localhost:5173/ts/frontend.ts"
        if development
        else "/static/bloomerp/js/dist/frontend-a.js"
    )
    assert assets["imports"] == {
        "@bloomerp/frontend": runtime,
        "@bloomerp/runtime": runtime,
    }
    expected_script = (
        "http://localhost:5174/ts/main.ts"
        if development
        else "/static/planner/frontend/planner-a.js"
    )
    assert assets["extensions"][0]["script"] == expected_script
    assert rendered.index('type="importmap"') < rendered.index('type="module"')
    assert "bloomerp-frontend-extensions" in rendered


def test_importmap_cannot_close_its_script_element() -> None:
    """Escape HTML delimiters while retaining valid import-map JSON."""
    rendered = str(
        frontend_importmap(
            {"@bloomerp/frontend": "https://cdn.example.com/</script>.js"}
        )
    )
    assert rendered.count("</script>") == 1
    payload = rendered.removeprefix('<script type="importmap">').removesuffix(
        "</script>"
    )
    assert json.loads(payload)["imports"]["@bloomerp/frontend"].endswith("</script>.js")
