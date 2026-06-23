from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from bloomerp.router import router
from bloomerp.models.forms.form import Form
from bloomerp.services.form_services import FormManager


def _cors_response(response: HttpResponse, request: HttpRequest | None = None) -> HttpResponse:
    requested_headers = ""
    if request is not None:
        requested_headers = request.headers.get("Access-Control-Request-Headers", "")

    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response["Access-Control-Allow-Headers"] = requested_headers or "Content-Type, X-Requested-With"
    response["Access-Control-Max-Age"] = "86400"
    return response


def _json_response(data: dict[str, Any], status: int = 200) -> JsonResponse:
    return _cors_response(JsonResponse(data, status=status))


def _parse_request_data(request: HttpRequest) -> dict[str, Any]:
    if request.content_type and "application/json" in request.content_type:
        try:
            raw_body = request.body.decode("utf-8") if request.body else "{}"
            payload = json.loads(raw_body or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    return request.POST.dict()


def _get_public_form(pk) -> tuple[Form | None, JsonResponse | None]:
    try:
        form = Form.objects.get(pk=pk)
    except Form.DoesNotExist:
        return None, _json_response({"detail": "Form not found."}, status=404)

    if not form.public_embed_enabled:
        return None, _json_response({"detail": "Form not found."}, status=404)

    if form.requires_authentication:
        return None, _json_response({"detail": "Authentication is required for this form."}, status=403)

    return form, None

@router.register(
    path="api/forms/<int_or_uuid:pk>/submit/",
    name="api_form_submit",
)
@csrf_exempt
@require_http_methods(["GET", "POST", "OPTIONS"])
def form_submit_view(request: HttpRequest, pk) -> HttpResponse:
    if request.method == "OPTIONS":
        return _cors_response(HttpResponse(status=204), request=request)

    form, error_response = _get_public_form(pk)
    if error_response is not None:
        return error_response
    assert form is not None

    if request.method == "GET":
        return _json_response(
            {
                "id": str(form.pk),
                "name": form.name,
                "description": form.description,
                "submitUrl": form.submit_api_url,
                "fields" : form.get_field_names()
            }
        )

    submission_response = FormManager(form).register_submission(
        _parse_request_data(request),
        request,
    )
    if not submission_response.submitted:
        return _json_response(
            {
                "submitted": False,
                "detail": submission_response.message,
            },
            status=400,
        )

    return _json_response(
        {
            "submitted": True,
            "detail": submission_response.message,
            "submissionId": str(submission_response.form_submission.pk)
            if submission_response.form_submission is not None
            else None,
        }
    )
