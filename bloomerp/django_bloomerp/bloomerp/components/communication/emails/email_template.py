"""Load template content and preview edited email bodies."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from bloomerp.router import router
from bloomerp.services.email_composer_services import (
    email_template_form, render_email_body, resolve_email_object,
    resolve_email_template, resolve_email_templates,
)


@router.register(path="components/communication/emails/template", url_name="components_email_template")
@login_required
@require_POST
def email_template(request: HttpRequest) -> HttpResponse:
    """Copy template content and return its context form, or preview edited content."""
    from bloomerp.components.communication.emails.reply_to_email import sanitize_quoted_email_html

    try:
        obj = resolve_email_object(request.user, request.POST)
        template = resolve_email_template(request.user, obj, request.POST.get("document_template_id"))
        if request.POST.get("preview") == "true":
            templates = resolve_email_templates(request.user, obj, request.POST)
            body = render_email_body(request.user, obj, templates, request.POST)
            return JsonResponse({"html": sanitize_quoted_email_html(body)})
        if template is None:
            return JsonResponse({"body": "", "form_html": ""})
        form = email_template_form(template, request.user, obj)
        return JsonResponse({
            "body": template.template,
            "form_html": render_to_string(
                "components/communication/emails/template_arguments.html", {"form": form}, request=request,
            ),
        })
    except ValidationError as exc:
        return JsonResponse({"errors": exc.messages}, status=400)
