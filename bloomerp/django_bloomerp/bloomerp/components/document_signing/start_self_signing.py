"""Choose a signer role, then materialize an authenticated self-signing session."""

import json
from uuid import uuid4

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework.exceptions import APIException

from bloomerp.document_signing.access import (
    PREPARATION_ROLE_FIELDS,
    get_signing_preparation,
    require_signing_access,
)
from bloomerp.document_signing.requests import (
    create_self_signing_request,
    signing_evidence,
)
from bloomerp.forms.document_signing.start_self_signing import StartSelfSigningForm
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router


@router.register(
    path="components/document_signing/start_self_signing/<str:file_id>",
    url_name="components_document_signing_start_self_signing",
)
@method_decorator([login_required, csrf_protect, ensure_csrf_cookie], name="dispatch")
class StartSelfSigningComponent(View):
    """Keep request creation on POST and make single-role preparations one-click operations."""

    def get(self, request: HttpRequest, file_id: str) -> HttpResponse:
        """Render an authorized role chooser without creating signing records."""
        manager = UserPolicyManager(request.user)
        try:
            preparation = get_signing_preparation(
                manager, file_id, request.GET.get("preparation_id", "")
            )
            roles = list(preparation.roles.all())
            for role in roles:
                require_signing_access(
                    role, manager, BloomerpPermission.VIEW, PREPARATION_ROLE_FIELDS
                )
        except APIException as error:
            return HttpResponse(
                str(error.detail), status=error.status_code, content_type="text/plain"
            )
        if not roles:
            return HttpResponse(
                "Add a signer role before signing.", status=400, content_type="text/plain"
            )
        component_id = f"start-self-signing-{uuid4().hex}"
        form = StartSelfSigningForm(
            roles=roles,
            auto_id=f"id_{component_id}_%s",
            initial={
                "preparation_id": preparation.pk,
                "revision": preparation.revision,
            },
        )
        return render(
            request,
            "components/document_signing/start_self_signing.html",
            {
                "component_id": component_id,
                "form": form,
                "file": preparation.original_file,
                "single_role": len(roles) == 1,
                "start_url": reverse(
                    "components_document_signing_start_self_signing",
                    kwargs={"file_id": file_id},
                ),
            },
        )

    def post(self, request: HttpRequest, file_id: str) -> JsonResponse:
        """Validate the chosen snapshot revision and return its idempotent signing component URL."""
        try:
            data = (
                json.loads(request.body)
                if request.content_type == "application/json"
                else request.POST
            )
            if not isinstance(data, dict):
                raise ValidationError("Submit a signing role and preparation revision.")
            manager = UserPolicyManager(request.user)
            preparation = get_signing_preparation(
                manager, file_id, data.get("preparation_id", "")
            )
            form = StartSelfSigningForm(roles=list(preparation.roles.all()), data=data)
            if not form.is_valid():
                return JsonResponse({"errors": form.errors}, status=400)
            recipient = create_self_signing_request(
                manager,
                file_id,
                **form.cleaned_data,
                evidence=signing_evidence(request.META),
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"errors": ["Submit valid JSON."]}, status=400)
        except ValidationError as error:
            return JsonResponse(
                {"errors": getattr(error, "message_dict", error.messages)}, status=400
            )
        except APIException as error:
            return JsonResponse({"errors": error.detail}, status=error.status_code)
        return JsonResponse(
            {
                "url": reverse(
                    "components_document_signing_sign_document",
                    kwargs={"recipient_id": recipient.pk},
                )
            }
        )
