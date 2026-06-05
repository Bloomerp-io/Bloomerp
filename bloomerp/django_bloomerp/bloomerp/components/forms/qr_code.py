import base64
from io import BytesIO

import qrcode
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from bloomerp.models.forms.form import Form
from bloomerp.router import router


def _form_submit_url(request: HttpRequest, form: Form) -> str:
    return request.build_absolute_uri(form.submit_url)


def _qr_code_png(url: str) -> bytes:
    image = qrcode.make(url)
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


@router.register(
    path="components/forms/<str:id>/qr-code/",
    url_name="components_forms_qr_code"
)
def qr_code(request: HttpRequest, id: str) -> HttpResponse:
    form = get_object_or_404(Form, id=id)
    submit_url = _form_submit_url(request, form)
    png = _qr_code_png(submit_url)

    if request.GET.get("download"):
        response = HttpResponse(png, content_type="image/png")
        response["Content-Disposition"] = (
            f'attachment; filename="form-{form.pk}-qr-code.png"'
        )
        return response

    return render(
        request,
        "components/forms/qr_code.html",
        context={
            "form": form,
            "submit_url": submit_url,
            "qr_code_data_uri": f"data:image/png;base64,{base64.b64encode(png).decode()}",
        }
    )
