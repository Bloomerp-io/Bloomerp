from pathlib import Path

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
        filename: str,
        add_readme: bool,
    ):
        match language:
            
            case "typescript":
                return TypescriptSdkGenerator(
                    path=path,
                    package_name=package_name,
                    force=force,
                    filename=filename,
                    add_readme=add_readme,
                )
            case "javascript":
                return JavaScriptSdkGenerator(
                    path=path,
                    package_name=package_name,
                    force=force,
                    filename=filename,
                    add_readme=add_readme,
                )
            case "python":
                return PythonSdkGenerator(
                    path=path,
                    package_name=package_name,
                    force=force,
                    filename=filename,
                    add_readme=add_readme,
                )
            case _:
                raise CommandError(
                    f"Unsupported SDK language '{language}'. Supported languages: typescript, javascript, python."
                )
