from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from bloomerp.sdk.javascript import JavaScriptSdkGenerator
from bloomerp.sdk.python import PythonSdkGenerator
from bloomerp.sdk.typescript import TypescriptSdkGenerator


class Command(BaseCommand):
    help = "Generate a typed SDK for Bloomerp APIs."

    def add_arguments(self, parser):
        parser.add_argument("path", type=str, help="Target directory for the generated SDK.")
        parser.add_argument(
            "--language",
            type=str,
            default="typescript",
            help="SDK language to generate. Supported: typescript, javascript, python.",
        )
        parser.add_argument(
            "--package-name",
            type=str,
            default=None,
            help="Optional package name for the generated SDK.",
        )
        parser.add_argument(
            "--filename",
            type=str,
            default=None,
            help="Optional filename for the generated SDK entry file. Defaults depend on the selected language.",
        )
        parser.add_argument(
            "--apps",
            type=str,
            default=None,
            help="Optional comma-separated app names to limit which app models are included in the generated SDK.",
        )
        parser.add_argument(
            "--add-readme",
            action="store_true",
            help="Also generate a README.md file in the target folder.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite generated files when they already exist.",
        )

    def handle(self, *args, **options):
        output_path = Path(options["path"]).expanduser()
        language = str(options["language"]).strip().lower()
        package_name = options.get("package_name")
        raw_filename = options.get("filename")
        filename = str(raw_filename).strip() if raw_filename is not None else None
        app_labels = self.parse_app_labels(options.get("apps"))
        add_readme = bool(options.get("add_readme"))
        force = bool(options.get("force"))

        if filename is not None and not filename:
            raise CommandError("Filename cannot be empty.")

        generator = self.get_generator(
            language=language,
            path=str(output_path),
            package_name=package_name,
            force=force,
            filename=filename,
            add_readme=add_readme,
            app_labels=app_labels,
        )
        try:
            generated_files = generator.generate()
        except FileExistsError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Generated {language} SDK in {output_path} ({len(generated_files)} files)."
            )
        )
        for generated_file in generated_files:
            self.stdout.write(str(generated_file))

    def get_generator(
        self,
        *,
        language: str,
        path: str,
        package_name: str | None,
        force: bool,
        filename: str | None,
        add_readme: bool,
        app_labels: list[str] | None,
    ):
        match language:
            case "typescript":
                return TypescriptSdkGenerator(
                    path=path,
                    package_name=package_name,
                    force=force,
                    filename=filename,
                    add_readme=add_readme,
                    app_labels=app_labels,
                )
            case "javascript":
                return JavaScriptSdkGenerator(
                    path=path,
                    package_name=package_name,
                    force=force,
                    filename=filename,
                    add_readme=add_readme,
                    app_labels=app_labels,
                )
            case "python":
                return PythonSdkGenerator(
                    path=path,
                    package_name=package_name,
                    force=force,
                    filename=filename,
                    add_readme=add_readme,
                    app_labels=app_labels,
                )
            case _:
                raise CommandError(
                    f"Unsupported SDK language '{language}'. Supported languages: typescript, javascript, python."
                )

    def parse_app_labels(self, raw_apps: str | None) -> list[str] | None:
        if raw_apps is None:
            return None

        raw_names = [part.strip() for part in str(raw_apps).split(",")]
        if not any(raw_names):
            raise CommandError("Apps cannot be empty.")

        normalized_labels: list[str] = []
        invalid_names: list[str] = []
        for raw_name in raw_names:
            if not raw_name:
                continue

            app_config = apps.app_configs.get(raw_name)
            if app_config is None:
                app_config = next(
                    (config for config in apps.get_app_configs() if config.name == raw_name),
                    None,
                )

            if app_config is None:
                invalid_names.append(raw_name)
                continue

            if app_config.label not in normalized_labels:
                normalized_labels.append(app_config.label)

        if invalid_names:
            raise CommandError(
                "Unknown app names: "
                + ", ".join(invalid_names)
                + ". Use Django app labels or full app config names."
            )

        return normalized_labels or None
