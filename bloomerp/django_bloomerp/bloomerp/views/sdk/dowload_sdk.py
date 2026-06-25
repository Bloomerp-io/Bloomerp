from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import FileResponse, HttpRequest, HttpResponse

from bloomerp.router import router
from bloomerp.views.base import BaseBloomerpView
from django.views.generic import TemplateView

@router.register(
    path="download-sdk",
    route_type="module",
    url_name="download_sdk",
    modules="misc",
    name="Download SDK"
)
class DownloadSDKView(BaseBloomerpView, TemplateView):
    template_name = "views/sdk/download.html"

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        language = str(request.POST.get("language", "typescript")).strip().lower() or "typescript"
        package_name = self._normalize_optional_value(request.POST.get("package_name"))
        filename = self._normalize_optional_value(request.POST.get("filename"))
        apps = self._normalize_optional_value(request.POST.get("apps"))
        add_readme = self._coerce_bool(request.POST.get("add_readme"))

        try:
            archive_stream = self._build_sdk_archive(
                language=language,
                package_name=package_name,
                filename=filename,
                apps=apps,
                add_readme=add_readme,
            )
        except CommandError as exc:
            self.add_message(str(exc), "danger")
            return super().get(request, *args, **kwargs)

        response = FileResponse(archive_stream, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="bloomerp-sdk-{language}.zip"'
        return response

    def _build_sdk_archive(
        self,
        *,
        language: str,
        package_name: str | None,
        filename: str | None,
        apps: str | None,
        add_readme: bool,
    ) -> BytesIO:
        with TemporaryDirectory(prefix="bloomerp-sdk-") as temp_dir:
            output_path = Path(temp_dir) / "sdk"
            command_args: list[str] = [
                str(output_path),
                "--language",
                language,
            ]

            if package_name:
                command_args.extend(["--package-name", package_name])
            if filename:
                command_args.extend(["--filename", filename])
            if apps:
                command_args.extend(["--apps", apps])
            if add_readme:
                command_args.append("--add-readme")

            call_command("create_sdk", *command_args)

            archive_stream = BytesIO()
            with ZipFile(archive_stream, mode="w", compression=ZIP_DEFLATED) as archive:
                for file_path in sorted(output_path.rglob("*")):
                    if not file_path.is_file():
                        continue
                    archive.write(file_path, arcname=str(file_path.relative_to(output_path)))

            archive_stream.seek(0)
            return archive_stream

    def _normalize_optional_value(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _coerce_bool(self, value: str | None) -> bool:
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    