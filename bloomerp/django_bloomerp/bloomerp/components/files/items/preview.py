from __future__ import annotations

import asyncio
import codecs
import csv
import mimetypes
import re
from collections.abc import AsyncIterator, Iterable, Iterator, Sequence
from io import StringIO
from pathlib import PurePath
from typing import TYPE_CHECKING, Any, TypedDict

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.handlers.asgi import ASGIRequest
from django.http import (
    FileResponse,
    Http404,
    HttpRequest,
    HttpResponse,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from bloomerp.router import router

if TYPE_CHECKING:
    from bloomerp.models.files.file_node import FileNode


MAX_PREVIEW_ROWS = 200
MAX_PREVIEW_COLUMNS = 50
MAX_PREVIEW_CELL_CHARACTERS = 2_000
MAX_TEXT_BYTES = 256 * 1024


def _file_extension(file: FileNode) -> str:
    """Read the original content extension from metadata, falling back to its key."""
    extension = file.metadata.extension
    return extension.lower() if extension is not None else PurePath(file.content.name).suffix.lstrip(".").lower()


def _media_chunks(file: FileNode, start: int, length: int) -> Iterator[bytes]:
    """Stream only the requested byte range and close storage after playback."""
    with file.content.open("rb") as source:
        source.seek(start)
        while length > 0:
            chunk = source.read(min(length, 64 * 1024))
            if not chunk:
                break
            length -= len(chunk)
            yield chunk


async def _async_media_chunks(
    file: FileNode, start: int, length: int
) -> AsyncIterator[bytes]:
    """Read bounded chunks off-thread so ASGI never buffers a synchronous file iterator."""
    chunks = _media_chunks(file, start, length)
    try:
        while (chunk := await asyncio.to_thread(next, chunks, None)) is not None:
            yield chunk
    finally:
        await asyncio.to_thread(chunks.close)


def _media_response(
    request: HttpRequest, file: FileNode
) -> HttpResponse | StreamingHttpResponse:
    """Stream authorized media under WSGI or ASGI, supporting PDF and player byte ranges."""
    metadata = file.metadata
    size = metadata.size if metadata.size is not None else file.content.size
    content_type = metadata.mime_type or mimetypes.guess_type(file.content.name)[0] or "application/octet-stream"
    requested_range = request.headers.get("Range")
    if requested_range:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested_range)
        start, end = 0, size - 1
        valid = match is not None and bool(match.group(1) or match.group(2))
        if valid:
            first, last = match.groups()
            if first:
                start = int(first)
                end = min(int(last), size - 1) if last else size - 1
            else:
                start = max(0, size - int(last))
            valid = 0 <= start <= end < size
        if not valid:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        response = StreamingHttpResponse(
            _async_media_chunks(file, start, end - start + 1)
            if isinstance(request, ASGIRequest)
            else _media_chunks(file, start, end - start + 1),
            status=206,
            content_type=content_type,
        )
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
        response["Content-Length"] = str(end - start + 1)
    elif isinstance(request, ASGIRequest):
        response = StreamingHttpResponse(
            _async_media_chunks(file, 0, size), content_type=content_type
        )
        response["Content-Length"] = str(size)
    else:
        response = FileResponse(file.content.open("rb"), content_type=content_type)
    response["Accept-Ranges"] = "bytes"
    response["X-Content-Type-Options"] = "nosniff"
    if _file_extension(file) == "pdf":
        response["X-Frame-Options"] = "SAMEORIGIN"
    return response


class SheetPreview(TypedDict):
    """Bounded spreadsheet values ready for escaped template rendering."""

    name: str
    columns: list[str]
    rows: list[list[str]]
    truncated: bool


def _sheet_preview(
    rows: Iterable[Sequence[Any]], *, name: str, truncated: bool = False
) -> SheetPreview:
    """Limit tabular rows, columns, and cell text before building the preview."""
    from itertools import islice

    sampled = list(islice(rows, MAX_PREVIEW_ROWS + 1))
    width = max((len(row) for row in sampled), default=0)
    truncated = (
        truncated or len(sampled) > MAX_PREVIEW_ROWS or width > MAX_PREVIEW_COLUMNS
    )
    width = min(width, MAX_PREVIEW_COLUMNS)
    values: list[list[str]] = []
    for row in sampled[:MAX_PREVIEW_ROWS]:
        cells: list[str] = []
        for index in range(width):
            value = row[index] if index < len(row) else None
            text = "" if value is None else str(value)
            if len(text) > MAX_PREVIEW_CELL_CHARACTERS:
                truncated = True
                text = text[:MAX_PREVIEW_CELL_CHARACTERS] + "…"
            cells.append(text)
        values.append(cells)
    return SheetPreview(
        name=name,
        columns=[str(index + 1) for index in range(width)],
        rows=values,
        truncated=truncated,
    )


def _text_preview(file: FileNode) -> tuple[str, bool]:
    """Read bounded UTF-8 or BOM-marked UTF-16 text without cutting a character."""
    with file.content.open("rb") as source:
        data = source.read(MAX_TEXT_BYTES + 1)
    truncated = len(data) > MAX_TEXT_BYTES
    encoding = (
        "utf-16"
        if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
        else "utf-8-sig"
    )
    decoder = codecs.getincrementaldecoder(encoding)()
    return decoder.decode(data[:MAX_TEXT_BYTES], final=not truncated), truncated


@router.register(
    path="components/files/preview_file/<str:file_id>/",
    name="components_preview_file",
)
@login_required
def preview_file(
    request: HttpRequest, file_id: str | FileNode
) -> HttpResponse | StreamingHttpResponse:
    """Render authorized, escaped previews for documents, sheets, images, and media."""
    from bloomerp.files.access import FileAccessManager
    from bloomerp.models.files.file_node import FileNode

    try:
        file = file_id if isinstance(file_id, FileNode) else get_object_or_404(FileNode, id=file_id)
    except (ValidationError, ValueError) as error:
        raise Http404("Invalid file identifier") from error
    if file.kind != FileNode.FileNodeKind.FILE or not file.content:
        raise Http404("Only file nodes can be previewed")
    if not FileAccessManager(request.user).can_read_file_node(file):
        return HttpResponse(status=403)

    preview_url = reverse("components_preview_file", kwargs={"file_id": file.pk})
    context: dict[str, Any] = {
        "file": file,
        "kind": "unsupported",
        "truncated": False,
        "media_url": f"{preview_url}?raw=1",
        "download_url": f"{preview_url}?download=1",
    }
    if request.GET.get("download") == "1":
        return FileResponse(
            file.content.open("rb"), as_attachment=True, filename=file.name
        )
    extension = _file_extension(file)
    if extension == "pdf":
        context["kind"] = "pdf"
    elif extension in {
        "apng",
        "avif",
        "bmp",
        "gif",
        "ico",
        "jfif",
        "jpg",
        "jpeg",
        "png",
        "svg",
        "webp",
    }:
        context["kind"] = "image"
    elif extension in {"mp4", "m4v", "webm", "ogv", "mov"}:
        context["kind"] = "video"
    elif extension in {"mp3", "wav", "ogg", "oga", "opus", "m4a", "aac", "flac"}:
        context["kind"] = "audio"
    elif extension in {"csv", "tsv"}:
        try:
            text, truncated = _text_preview(file)
            context.update(
                kind="sheets",
                sheets=[
                    _sheet_preview(
                        csv.reader(
                            StringIO(text),
                            delimiter="\t" if extension == "tsv" else ",",
                        ),
                        name=file.name,
                        truncated=truncated,
                    )
                ],
            )
        except (UnicodeError, OSError, csv.Error):
            context["kind"] = "unsupported"
    elif extension in {
        "txt",
        "log",
        "md",
        "rst",
        "json",
        "xml",
        "yaml",
        "yml",
        "ini",
        "toml",
        "html",
        "htm",
        "css",
        "js",
        "ts",
        "py",
        "sql",
    }:
        try:
            text, truncated = _text_preview(file)
            context.update(kind="text", text=text, truncated=truncated)
        except (UnicodeError, OSError):
            context["kind"] = "unsupported"
    if request.GET.get("raw") == "1":
        if context["kind"] not in {"pdf", "image", "video", "audio"}:
            return HttpResponse(status=400)
        return _media_response(request, file)
    return render(request, "components/files/preview.html", context)
