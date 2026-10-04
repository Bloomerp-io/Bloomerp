"""One removable, private job model for bounded uploaded-file extraction."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta
from typing import Any, ClassVar
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core import signing
from django.core.files.base import ContentFile
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.http import HttpRequest
from django.utils import timezone
from django.utils.crypto import salted_hmac
from rest_framework.exceptions import NotFound, ValidationError

from bloomerp.models.definition import (
    ActivityLogSettings,
    ApiSettings,
    BloomerpModelConfig,
    StringSearchSettings,
)

MAX_RESULT_BYTES = 8 * 1024 * 1024
MAX_STORED_BYTES = 12 * 1024 * 1024
MAX_RESPONSE_BYTES = 48 * 1024
MAX_RECORDS = 20000


def extraction_expiry() -> datetime:
    """Expire private extraction data one day after job creation."""
    return timezone.now() + timedelta(days=1)


def extraction_start_deadline() -> datetime:
    """Bound queue waiting independently of broker acceptance."""
    return timezone.now() + timedelta(minutes=2)


class FileExtraction(models.Model):
    """Keep ownership, lifecycle and bounded result access in one private record."""

    bloomerp_config = BloomerpModelConfig(
        is_internal=True,
        api_settings=ApiSettings(enable_auto_generation=False),
        string_search_settings=StringSearchSettings(allow_global_search=False),
        activity_log_settings=ActivityLogSettings(enabled=False),
    )

    class Status(models.TextChoices):
        """Expose explicit terminal outcomes without parser exception details."""

        QUEUED = "queued"
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        UNAVAILABLE = "unavailable"
        EXPIRED = "expired"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    source_file = models.ForeignKey(
        "bloomerp.File", null=True, on_delete=models.SET_NULL
    )
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.QUEUED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    start_deadline = models.DateTimeField(default=extraction_start_deadline)
    expires_at = models.DateTimeField(default=extraction_expiry)
    error_code = models.CharField(max_length=40, blank=True)
    result = models.FileField(
        upload_to="bloomerp/extractions/%Y/%m/%d", blank=True, max_length=255
    )
    manifest = models.JSONField(default=dict)

    class Meta:
        """Avoid automatic CRUD permissions for internal extraction contents."""

        db_table = "bloomerp_file_extraction"
        default_permissions = ()
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["status", "expires_at"], name="file_extract_status_exp_idx"
            )
        ]

    @classmethod
    def authorized(cls, request: HttpRequest, job_id: Any) -> FileExtraction:
        """Resolve only the current owner's job and recheck live source permissions."""
        from bloomerp.services.file_permission_services import user_can_view_file

        if not request.user.is_authenticated or not request.user.is_active:
            raise NotFound("Extraction unavailable")
        job = (
            cls.objects.select_related("source_file")
            .filter(pk=job_id, requested_by=request.user)
            .first()
        )
        if job is None or job.source_file is None or not job.source_file.persisted:
            raise NotFound("Extraction unavailable")
        if not user_can_view_file(request, job.source_file):
            raise NotFound("Extraction unavailable")
        job.refresh_lifecycle()
        return job

    def refresh_lifecycle(self) -> None:
        """Expire leases with conditional updates so stale readers cannot clobber workers."""
        now = timezone.now()
        rows = type(self).objects.filter(pk=self.pk)
        if self.expires_at <= now:
            rows.update(
                status=self.Status.EXPIRED,
                error_code="expired",
                finished_at=now,
                updated_at=now,
            )
            self.refresh_from_db()
            self.delete_result()
        elif self.status == self.Status.QUEUED and self.start_deadline <= now:
            rows.filter(status=self.Status.QUEUED, start_deadline__lte=now).update(
                status=self.Status.UNAVAILABLE,
                error_code="worker_start_timeout",
                finished_at=now,
                updated_at=now,
            )
            self.refresh_from_db()
        elif (
            self.status == self.Status.RUNNING
            and self.started_at
            and self.started_at + timedelta(seconds=150) <= now
        ):
            rows.filter(
                status=self.Status.RUNNING, started_at__lte=now - timedelta(seconds=150)
            ).update(
                status=self.Status.FAILED,
                error_code="execution_timeout",
                finished_at=now,
                updated_at=now,
            )
            self.refresh_from_db()

    def finish(self, status: str, error_code: str = "") -> None:
        """Persist a fixed error code only if this observed lifecycle state is still current."""
        type(self).objects.filter(
            pk=self.pk, status=self.status, updated_at=self.updated_at
        ).update(
            status=status,
            error_code=error_code,
            finished_at=timezone.now(),
            updated_at=timezone.now(),
        )
        self.refresh_from_db()

    def delete_result(self) -> None:
        """Remove expired storage; retain its reference for a later retry if storage fails."""
        if self.result:
            name = self.result.name
            try:
                self.result.storage.delete(name)
            except Exception:  # noqa: BLE001 - storage provider errors must not expose private paths.
                return
            type(self).objects.filter(pk=self.pk, result=name).update(
                result="", manifest={}, updated_at=timezone.now()
            )
            self.refresh_from_db()

    @classmethod
    def cleanup_expired(cls) -> None:
        """Reclaim a bounded batch opportunistically without adding a scheduler/service."""
        for job in cls.objects.filter(expires_at__lte=timezone.now()).exclude(
            result=""
        )[:20]:
            job.refresh_lifecycle()

    def describe(self) -> dict[str, Any]:
        """Return small status metadata and a bounded index, never a storage URL."""
        return {
            "job_id": str(self.pk),
            "status": self.status,
            "error_code": self.error_code or None,
            "expires_at": self.expires_at.isoformat(),
            "manifest": self.manifest if self.status == self.Status.SUCCEEDED else {},
            "poll_after_seconds": 3
            if self.status in (self.Status.QUEUED, self.Status.RUNNING)
            else None,
            "content_is_untrusted": True,
        }

    @staticmethod
    def validate_document(document: Any) -> dict[str, Any]:
        """Reject malformed or oversized record metadata before it can reach an MCP response."""
        if (
            not isinstance(document, dict)
            or not isinstance(document.get("records"), list)
            or len(document["records"]) > MAX_RECORDS
        ):
            raise ValueError("Invalid result")
        text_limits = {"text": 16000, "section": 255, "sheet": 31, "cell": 16}
        number_limits = {
            "id": MAX_RECORDS,
            "page": 100,
            "row": 1048576,
            "column": 16384,
        }
        for record in document["records"]:
            if (
                not isinstance(record, dict)
                or set(record) - set(text_limits) - set(number_limits)
                or "id" not in record
                or "text" not in record
            ):
                raise ValueError("Invalid record")
            for key, value in record.items():
                if key in text_limits and (
                    not isinstance(value, str) or len(value) > text_limits[key]
                ):
                    raise ValueError("Invalid record text")
                if key in number_limits and (
                    type(value) is not int or not 1 <= value <= number_limits[key]
                ):
                    raise ValueError("Invalid record coordinate")
        index = document.get("index", {})
        if not isinstance(index, dict) or set(index) - {"pages", "sections", "sheets"}:
            raise ValueError("Invalid result index")
        count = 0
        for entries in index.values():
            if not isinstance(entries, list):
                raise TypeError("Invalid result index")
            count += len(entries)
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) - {
                    "page",
                    "section",
                    "sheet",
                    "text",
                }:
                    raise ValueError("Invalid index entry")
                for key, value in entry.items():
                    if key == "page":
                        if type(value) is not int or not 1 <= value <= 100:
                            raise ValueError("Invalid index page")
                    elif not isinstance(value, str) or len(value) > 255:
                        raise ValueError("Invalid index text")
        if (
            count > 512
            or not isinstance(document.get("format", ""), str)
            or len(document.get("format", "")) > 8
            or type(document.get("truncated", False)) is not bool
        ):
            raise ValueError("Invalid result metadata")
        for key in ("warnings", "truncation_reasons"):
            values = document.get(key, [])
            if (
                not isinstance(values, list)
                or len(values) > 16
                or any(
                    not isinstance(value, str) or len(value) > 255 for value in values
                )
            ):
                raise ValueError("Invalid result warnings")
        return document

    def result_cipher(self, secret: str) -> Fernet:
        """Derive a job-specific encryption key without writing credentials to storage."""
        key = salted_hmac(
            "bloomerp.file-extraction", str(self.pk), secret=secret, algorithm="sha256"
        ).digest()
        return Fernet(base64.urlsafe_b64encode(key))

    def store_result(self, document: dict[str, Any]) -> str:
        """Encrypt authenticated result bytes even when ordinary media storage is public."""
        self.validate_document(document)
        raw = json.dumps(
            document, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        if len(raw) > MAX_RESULT_BYTES:
            raise ValueError("result_size_limit")
        encrypted = self.result_cipher(settings.SECRET_KEY).encrypt(raw)
        return self.result.storage.save(
            f"bloomerp/extractions/{uuid4()}.bin", ContentFile(encrypted)
        )

    def decrypt_result(self, encrypted: bytes) -> bytes:
        """Read current or rotated application keys while never returning ciphertext errors."""
        for secret in [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]:
            try:
                return self.result_cipher(secret).decrypt(encrypted)
            except InvalidToken:
                continue
        raise ValueError("Invalid result ciphertext")

    def read_result(self, request: HttpRequest) -> dict[str, Any]:
        """Reauthorize every read and enforce the stored document's hard byte ceiling."""
        current = self.authorized(request, self.pk)
        if current.status != self.Status.SUCCEEDED or not current.result:
            return {}
        try:
            with current.result.storage.open(current.result.name, "rb") as handle:
                encrypted = handle.read(MAX_STORED_BYTES + 1)
            if len(encrypted) > MAX_STORED_BYTES:
                raise ValueError("Oversized stored result")
            raw = self.decrypt_result(encrypted)
            if len(raw) > MAX_RESULT_BYTES:
                raise ValueError("Oversized result")
            document = json.loads(raw)
            self.validate_document(document)
            return document
        except Exception:  # noqa: BLE001 - sanitize storage-provider and corrupt-result failures.
            current.finish(self.Status.FAILED, "result_unavailable")
            return {}

    def get_results(
        self,
        request: HttpRequest,
        *,
        page: int | None = None,
        section: str | None = None,
        sheet: str | None = None,
        cell_range: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Read bounded page/section/sheet ranges with a signed continuation into long text."""
        current = self.authorized(request, self.pk)
        payload = current.describe()
        if current.status != self.Status.SUCCEEDED:
            return payload
        if not 1 <= limit <= 100:
            raise ValidationError("limit must be between 1 and 100")
        bounds = None
        if cell_range:
            from openpyxl.utils.cell import range_boundaries

            try:
                bounds = range_boundaries(cell_range)
                if (
                    not sheet
                    or any(value is None for value in bounds)
                    or not (
                        1 <= bounds[0] <= bounds[2] <= 16384
                        and 1 <= bounds[1] <= bounds[3] <= 1048576
                    )
                ):
                    raise ValueError("Invalid range")
            except (ValueError, TypeError):
                raise ValidationError(
                    "Provide sheet and a valid bounded A1 cell_range"
                ) from None
        selection = [page, section, sheet, cell_range]
        position, text_offset = 0, 0
        if cursor:
            try:
                token = signing.loads(
                    cursor, salt="bloomerp.file-extraction", max_age=86400
                )
                if token["job"] != str(self.pk) or token["selection"] != selection:
                    raise ValueError("Mismatched cursor")
                position, text_offset = int(token["position"]), int(token["offset"])
                if (
                    position < 0
                    or position > MAX_RECORDS
                    or text_offset < 0
                    or text_offset > 16000
                ):
                    raise ValueError("Invalid cursor position")
            except (signing.BadSignature, ValueError, KeyError, TypeError):
                raise ValidationError("Invalid or expired cursor") from None
        document = current.read_result(request)
        if not document:
            current.refresh_from_db()
            return current.describe()
        records = document["records"]
        output: list[dict[str, Any]] = []
        next_position, next_offset = position, text_offset
        for index in range(position, len(records)):
            record = records[index]
            next_position, next_offset = index + 1, 0
            if (
                page is not None
                and record.get("page") != page
                or section is not None
                and record.get("section") != section
                or sheet is not None
                and record.get("sheet") != sheet
            ):
                continue
            if bounds and not (
                bounds[0] <= record.get("column", 0) <= bounds[2]
                and bounds[1] <= record.get("row", 0) <= bounds[3]
            ):
                continue
            offset = text_offset if index == position else 0
            text = str(record.get("text", ""))
            # Conservative ASCII JSON sizing also bounds Unicode-heavy client output.
            remaining = (
                MAX_RESPONSE_BYTES
                - len(json.dumps(payload, ensure_ascii=True).encode())
                - len(json.dumps(output, ensure_ascii=True).encode())
                - 8192
            )
            if remaining < 1024 or len(output) >= limit:
                next_position, next_offset = index, offset
                break
            take = min(len(text) - offset, remaining // 12, 8000)
            entry = {
                key: value
                for key, value in record.items()
                if key in {"id", "page", "section", "sheet", "row", "column", "cell"}
            }
            entry.update(
                text=text[offset : offset + take],
                text_offset=offset,
                text_continues=offset + take < len(text),
            )
            output.append(entry)
            if offset + take < len(text):
                next_position, next_offset = index, offset + take
                break
        has_more = next_position < len(records)
        payload.update(
            records=output,
            truncated=bool(document.get("truncated")) or has_more,
            source_truncated=bool(document.get("truncated")),
            next_cursor=None,
        )
        if has_more:
            payload["next_cursor"] = signing.dumps(
                {
                    "job": str(self.pk),
                    "selection": selection,
                    "position": next_position,
                    "offset": next_offset,
                },
                salt="bloomerp.file-extraction",
                compress=True,
            )
        return payload


@receiver(post_delete, sender=FileExtraction)
def delete_extraction_storage(
    sender: type[FileExtraction], instance: FileExtraction, **kwargs: Any
) -> None:
    """Clean private result bytes when a job or its owner is deleted."""
    if instance.result:
        instance.result.delete(save=False)
