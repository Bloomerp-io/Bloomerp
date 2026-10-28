"""Exercise optional frontend scaffolding and the app packaging boundary."""

import json
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from bloomerp.cli.app.build import build_app_wheel
from bloomerp.cli.app.init import create_app
from bloomerp.cli.frontend import build_frontend, create_frontend
from bloomerp.cli.main import main


@pytest.fixture(autouse=True)
def bundled_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a local framework API independently of repository build artifacts."""
    package = tmp_path / "framework-api"
    (package / "dist").mkdir(parents=True)
    (package / "package.json").write_text(
        json.dumps({"name": "@bloomerp/frontend", "version": "1.2.3"})
    )
    (package / "dist/index.js").write_text("export {};\n")
    (package / "dist/index.d.ts").write_text("export {};\n")
    (package / "dist/BaseComponent.d.ts").write_text("export {};\n")
    monkeypatch.setattr("bloomerp.cli.frontend.FRONTEND_API_PACKAGE", package)
    return package


@pytest.mark.parametrize("frontend", [False, True])
def test_app_frontend_is_opt_in(tmp_path: Path, frontend: bool) -> None:
    """Only apps explicitly opting in receive a typed frontend and descriptor."""
    app = create_app("sales-tools", tmp_path, frontend=frontend)
    assert (app / "frontend/package.json").is_file() is frontend
    assert (app / "static/sales_tools/frontend.json").is_file() is frontend
    if frontend:
        manifest = json.loads((app / "frontend/package.json").read_text())
        assert (
            manifest["dependencies"]["@bloomerp/frontend"]
            == "file:./.bloomerp/frontend-api"
        )
        assert (app / "frontend/.bloomerp/frontend-api/dist/index.d.ts").is_file()
        assert "sales_tools:example" in (app / "frontend/ts/main.ts").read_text()
        assert "__APP_LABEL__" not in (app / "frontend/vite.config.ts").read_text()


def test_frontend_cli_supports_new_and_existing_apps(bundled_api: Path) -> None:
    """Both creation paths produce discoverable assets and preserve authored files."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        initialized = runner.invoke(
            main,
            ["project", "init", ".", "--name", "Frontend", "--no-app", "--no-input"],
        )
        assert initialized.exit_code == 0, initialized.output
        created = runner.invoke(main, ["app", "init", "planner", "--frontend"])
        assert created.exit_code == 0, created.output
        assert Path("apps/planner/frontend/ts/main.ts").is_file()
        created = runner.invoke(main, ["app", "init", "reports"])
        assert created.exit_code == 0, created.output
        added = runner.invoke(main, ["app", "frontend", "reports"])
        assert added.exit_code == 0, added.output
        entry = Path("apps/reports/frontend/ts/main.ts")
        entry.write_text("// authored component registration\n")
        repeated = runner.invoke(main, ["app", "frontend", "reports"])
        assert repeated.exit_code != 0
        assert "no files were changed" in repeated.output
        assert entry.read_text() == "// authored component registration\n"
        (bundled_api / "dist/index.d.ts").write_text("// upgraded framework API\n")
        stale = Path("apps/reports/frontend/.bloomerp/frontend-api/dist/removed.d.ts")
        stale.write_text("// obsolete API\n")
        refreshed = runner.invoke(main, ["app", "frontend", "reports", "--sync-api"])
        assert refreshed.exit_code == 0, refreshed.output
        assert not stale.exists()
        assert (
            Path(
                "apps/reports/frontend/.bloomerp/frontend-api/dist/index.d.ts"
            ).read_text()
            == "// upgraded framework API\n"
        )
        assert entry.read_text() == "// authored component registration\n"


def test_scaffold_reports_missing_bundled_api(
    tmp_path: Path, bundled_api: Path
) -> None:
    """Explain source-build requirements without writing a partial frontend scaffold."""
    (bundled_api / "dist/index.d.ts").unlink()
    with pytest.raises(click.ClickException, match="packages/frontend"):
        create_frontend(tmp_path / "planner")
    assert not (tmp_path / "planner/frontend").exists()


@pytest.mark.parametrize("locked", [False, True])
def test_frontend_build_uses_lockfile_when_present(
    tmp_path: Path, locked: bool, bundled_api: Path
) -> None:
    """Builds use npm ci for locked workspaces and always compile before packaging."""
    create_frontend(tmp_path / "planner")
    workspace = tmp_path / "planner/frontend"
    if locked:
        (workspace / "package-lock.json").write_text("{}")
    (bundled_api / "dist/index.d.ts").write_text(
        "// API from newly installed framework\n"
    )
    with (
        patch("bloomerp.cli.frontend.shutil.which", return_value="/usr/bin/npm"),
        patch("bloomerp.cli.frontend.subprocess.run") as run,
    ):
        build_frontend(tmp_path / "planner")
    assert run.call_args_list[0].args[0] == [
        "/usr/bin/npm",
        "ci" if locked else "install",
    ]
    assert run.call_args_list[1].args[0] == ["/usr/bin/npm", "run", "build"]
    assert run.call_args_list[1].kwargs == {"cwd": workspace, "check": True}
    assert (
        workspace / ".bloomerp/frontend-api/dist/index.d.ts"
    ).read_text() == "// API from newly installed framework\n"


def test_failed_frontend_build_stops_packaging(tmp_path: Path) -> None:
    """A failed npm build cannot silently publish stale frontend assets."""
    create_frontend(tmp_path / "planner")
    with (
        patch("bloomerp.cli.frontend.shutil.which", return_value="npm"),
        patch(
            "bloomerp.cli.frontend.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "npm"),
        ),
        pytest.raises(click.ClickException, match="app wheel was not built"),
    ):
        build_frontend(tmp_path / "planner")


def test_app_wheel_keeps_compiled_frontend_assets(tmp_path: Path) -> None:
    """Package built static assets while excluding frontend sources and dependencies."""
    app = create_app("planner", tmp_path, frontend=True)
    runner = CliRunner()

    def fake_wheel_build(command: list[str], *, check: bool) -> None:
        """Inspect the packaging tree and emit a minimal wheel for the CLI to copy."""
        staged = Path(command[-1]) / "apps/planner"
        assert (staged / "static/planner/frontend/main.js").is_file()
        assert (staged / "static/planner/frontend/manifest.json").is_file()
        assert not (staged / "frontend").exists()
        output = Path(command[command.index("--outdir") + 1])
        output.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output / "planner-0.1.0-py3-none-any.whl", "w") as archive:
            archive.write(
                staged / "static/planner/frontend/main.js",
                "apps/planner/static/planner/frontend/main.js",
            )

    def fake_frontend_build(app_dir: Path) -> None:
        """Produce assets where the generated app's Vite configuration writes them."""
        output = app_dir / "static/planner/frontend"
        output.mkdir()
        (output / "main.js").write_text("export {};\n")
        (output / "manifest.json").write_text("{}")

    with (
        runner.isolated_filesystem(),
        patch(
            "bloomerp.cli.app.build.read_app_state",
            return_value=SimpleNamespace(app_id=None),
        ),
        patch("bloomerp.cli.app.build.build_frontend", side_effect=fake_frontend_build),
        patch("bloomerp.cli.app.build.subprocess.run", side_effect=fake_wheel_build),
    ):
        wheel = build_app_wheel(app, tmp_path / "dist")
    with zipfile.ZipFile(wheel) as archive:
        assert "apps/planner/static/planner/frontend/main.js" in archive.namelist()
