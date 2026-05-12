import base64

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.html import format_html

from bloomerp.models.files.file import File
from bloomerp.router import router
from bloomerp.components.files import _user_can_view_file

@router.register(
    path="components/files/preview_file/<str:file_id>/",
    name="components_preview_file",
)
@login_required
def preview_file(request:HttpRequest, file_id:str) -> HttpResponse:
    """Component to preview a particular file

    Args:
        request (HttpRequest): the request object
        file_id (str): the file id
    """
    file = get_object_or_404(File, id=file_id)
    if not _user_can_view_file(request, file):
        return HttpResponse(status=403)

    extension = file.file_extension.lower()
    if extension == "pdf":
        with file.file.open("rb") as pdf_file:
            encoded_pdf = base64.b64encode(pdf_file.read()).decode("ascii")

        return HttpResponse(format_html(
            """
            <div class="h-[calc(72vh-73px)] bg-slate-900">
                <iframe
                    src="data:application/pdf;base64,{}"
                    class="h-full w-full"
                    title="{}"
                ></iframe>
            </div>
            """,
            encoded_pdf,
            file.name or "PDF preview",
        ))

    if extension in {"apng", "avif", "gif", "jpg", "jpeg", "png", "svg", "webp"}:
        return HttpResponse(format_html(
            """
            <div class="flex h-[calc(72vh-73px)] items-center justify-center bg-slate-950 p-6">
                <img
                    src="{}"
                    alt="{}"
                    class="max-h-full max-w-full rounded-lg object-contain shadow-lg"
                >
            </div>
            """,
            file.file.url,
            file.name or "File preview",
        ))

    return HttpResponse(format_html(
        """
        <div class="flex h-[calc(72vh-73px)] items-center justify-center bg-slate-50 px-8 text-center">
            <div class="max-w-sm">
                <div class="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-white text-slate-400 shadow-xs">
                    <i class="fa-regular fa-file text-2xl" aria-hidden="true"></i>
                </div>
                <h4 class="text-sm font-semibold text-slate-900">Preview unavailable</h4>
                <p class="mt-2 text-sm text-slate-500">{} cannot be previewed here.</p>
                <a href="{}" class="btn btn-primary btn-sm mt-4" download>
                    <i class="fa-solid fa-download" aria-hidden="true"></i>
                    <span>Download</span>
                </a>
            </div>
        </div>
        """,
        file.name or "This file",
        file.file.url,
    ))
