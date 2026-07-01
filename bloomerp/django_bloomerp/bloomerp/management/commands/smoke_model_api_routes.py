from http import HTTPStatus
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Smoke-check generated model API routes on a deployed Bloomerp host."

    def add_arguments(self, parser):
        parser.add_argument("--base-url", required=True)
        parser.add_argument("--public-path", default="/api/stripe_products/")
        parser.add_argument("--authenticated-path", default="/api/projects/")
        parser.add_argument("--api-key", default="")
        parser.add_argument("--timeout", type=float, default=10.0)

    def handle(self, *args, **options):
        base_url = options["base_url"].rstrip("/") + "/"
        timeout = options["timeout"]
        api_key = options["api_key"].strip()

        checks = [
            (
                "public",
                options["public_path"],
                {HTTPStatus.OK},
                {},
            ),
            (
                "authenticated",
                options["authenticated_path"],
                {HTTPStatus.OK, HTTPStatus.UNAUTHORIZED},
                {"Authorization": f"Bearer {api_key}"} if api_key else {},
            ),
        ]

        failures = []
        for label, path, allowed_statuses, headers in checks:
            status_code = self._request_status(
                urljoin(base_url, path.lstrip("/")),
                headers=headers,
                timeout=timeout,
            )

            if status_code in allowed_statuses:
                self.stdout.write(
                    self.style.SUCCESS(f"{label}: {path} returned {status_code}")
                )
                continue

            failures.append(f"{label}: {path} returned {status_code}")

        if failures:
            raise CommandError("; ".join(failures))

    def _request_status(self, url: str, *, headers: dict[str, str], timeout: float) -> int:
        request = Request(url, headers={"Accept": "application/json", **headers})
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.status
        except HTTPError as error:
            return error.code
        except URLError as error:
            raise CommandError(f"{url} request failed: {error}") from error
