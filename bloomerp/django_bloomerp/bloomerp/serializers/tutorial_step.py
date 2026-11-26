"""Validate the shared tutorial step editor fields and expose row summaries."""

from collections.abc import Collection
from typing import Any, TypedDict
from urllib.parse import unquote
from uuid import UUID

from bs4 import BeautifulSoup
from django.urls import NoReverseMatch, Resolver404, get_script_prefix, resolve, reverse
from django.utils.translation import gettext as _
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from bloomerp.models.tutorial import Tutorial, TutorialStep
from bloomerp.models.tutorial.tutorial_step import empty_tutorial_step_interaction
from bloomerp.utils.navigation import supports_main_content_navigation
from bloomerp.utils.rich_text import sanitize_html


class TutorialStepFieldsSerializer(serializers.Serializer):
    """Validate the shared presentation settings for the step editor."""

    name = serializers.CharField(max_length=255)
    text = serializers.CharField(max_length=100_000, required=False, allow_blank=True)
    size = serializers.ChoiceField(choices=TutorialStep.Size.choices, required=False)
    include_backdrop = serializers.BooleanField()
    show_as_tooltip = serializers.BooleanField(required=False)
    advance_mode = serializers.ChoiceField(
        choices=TutorialStep.AdvanceMode.choices, required=False
    )
    advance_delay_ms = serializers.IntegerField(
        min_value=0, max_value=2_147_483_647, required=False
    )
    advance_url_pattern = serializers.CharField(
        max_length=2048, required=False, allow_blank=True
    )
    hide_next_button = serializers.BooleanField(required=False)
    interaction = serializers.JSONField(required=False)

    def validate_interaction(self, value: Any) -> dict[str, Any]:
        """Validate the structured highlights and action lists before storing them."""
        serializer = TutorialStepInteractionSerializer(data=value)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def validate_text(self, value: str) -> str:
        """Sanitize the description and store empty editor markup as a blank value."""
        content = sanitize_html(value, allow_images=True)
        document = BeautifulSoup(content, "html.parser")
        if not document.get_text(strip=True) and document.find("img") is None:
            return ""
        return content


class TutorialHighlightSerializer(serializers.Serializer):
    """Store a named target and its backdrop interaction setting."""

    id = serializers.CharField(max_length=64)
    label = serializers.CharField(max_length=120)
    selector = serializers.CharField(max_length=1024)
    allow_interaction = serializers.BooleanField()


class TutorialStepActionSerializer(serializers.Serializer):
    """Describe one supported browser action on a selected or separately picked element."""

    kind = serializers.ChoiceField(choices=("click", "fill", "select", "wait"))
    highlight_id = serializers.CharField(max_length=64, allow_blank=True, default="")
    selector = serializers.CharField(max_length=1024, allow_blank=True, default="")
    value = serializers.CharField(max_length=2048, allow_blank=True, trim_whitespace=False, default="")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Require a single target and retain values only for input actions."""
        if bool(attrs["highlight_id"]) == bool(attrs["selector"]):
            raise ValidationError(_("Choose one highlight or pick a separate element."))
        if attrs["kind"] not in ("fill", "select"):
            attrs["value"] = ""
        return attrs


class TutorialStepInteractionSerializer(serializers.Serializer):
    """Keep related target references and ordered actions together."""

    highlights = TutorialHighlightSerializer(many=True)
    tooltip_highlight_id = serializers.CharField(max_length=64, allow_blank=True, default="")
    advance_highlight_id = serializers.CharField(max_length=64, allow_blank=True, default="")
    before = TutorialStepActionSerializer(many=True)
    after = TutorialStepActionSerializer(many=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Reject duplicate highlight IDs and references to missing highlights."""
        ids = {highlight["id"] for highlight in attrs["highlights"]}
        if len(ids) != len(attrs["highlights"]):
            raise ValidationError({"highlights": _("Each highlight must have a unique ID.")})
        if len({highlight["selector"] for highlight in attrs["highlights"]}) != len(ids):
            raise ValidationError({"highlights": _("Each element can only be highlighted once per step.")})
        for field in ("tooltip_highlight_id", "advance_highlight_id"):
            if attrs[field] and attrs[field] not in ids:
                raise ValidationError({field: _("Choose a highlight from this step.")})
        for phase in ("before", "after"):
            if any(action["highlight_id"] and action["highlight_id"] not in ids for action in attrs[phase]):
                raise ValidationError({phase: _("Choose a highlight from this step for each action.")})
        return attrs


class TutorialStepSummarySerializer(serializers.Serializer):
    """Return the editable row's identifier, display name, and sequence."""

    id = serializers.UUIDField(read_only=True)
    sequence = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class TutorialRevisionStepsSerializer(serializers.Serializer):
    """Return step summaries in the revision's current order."""

    steps = TutorialStepSummarySerializer(many=True, read_only=True)


class TutorialRevisionStepsQuery(serializers.Serializer):
    """Identify the published revision addressed by a learner action."""

    revision_id = serializers.UUIDField()


class TutorialPreviewStepSerializer(serializers.Serializer):
    """Describe what the preview can show for one step."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    text = serializers.CharField(read_only=True)
    size = serializers.ChoiceField(choices=TutorialStep.Size.choices, read_only=True)
    destination_url = serializers.CharField(read_only=True, allow_null=True)
    include_backdrop = serializers.BooleanField(read_only=True)
    show_as_tooltip = serializers.BooleanField(read_only=True)
    advance_mode = serializers.ChoiceField(
        choices=TutorialStep.AdvanceMode.choices, read_only=True
    )
    advance_delay_ms = serializers.IntegerField(read_only=True)
    advance_url_pattern = serializers.CharField(read_only=True)
    hide_next_button = serializers.BooleanField(read_only=True)
    interaction = serializers.JSONField(read_only=True)


class TutorialIntroductionSerializer(serializers.Serializer):
    """Describe the welcome screen shown before the first step."""

    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)


class TutorialRevisionPreviewSerializer(serializers.Serializer):
    """Return the introduction and authored steps in presentation order."""

    introduction = TutorialIntroductionSerializer(read_only=True)
    steps = TutorialPreviewStepSerializer(many=True, read_only=True)


def serialize_tutorial_introduction(
    tutorial: Tutorial, *, include_description: bool = True
) -> dict[str, str]:
    """Provide the tutorial title and sanitize the readable description."""
    return {
        "name": str(tutorial),
        "description": sanitize_html(tutorial.description, allow_images=True)
        if include_description
        else "",
    }


class ReorderTutorialStepsSerializer(serializers.Serializer):
    """Accept every step ID in the intended order for one revision."""

    step_ids = serializers.ListField(child=serializers.UUIDField())

    def validate_step_ids(self, value: list[UUID]) -> list[UUID]:
        """Require each step to appear once in the submitted order."""
        if len(value) != len(set(value)):
            raise serializers.ValidationError(_("Each step must appear once."))
        return value


class StepPageFields(TypedDict):
    """Store a concrete route and its arguments for a tutorial step."""

    destination_route: str
    destination_kwargs: dict[str, str | int]


STEP_PAGE_FIELDS = frozenset(StepPageFields.__annotations__)


def validate_local_step_path(page_path: str, field: str) -> str:
    """Validate and decode a local URL path for the specified tutorial field."""
    path = unquote(page_path)
    if (
        not page_path.startswith("/")
        or path.startswith("//")
        or "\\" in path
        or "?" in page_path
        or "#" in page_path
        or any(ord(char) < 32 for char in path)
    ):
        raise ValidationError({field: _("Enter a local path starting with /.")})
    return path


def resolve_step_page(page_path: str) -> StepPageFields:
    """Resolve an exact page, or keep the current page when the field is blank."""
    if not page_path:
        return {"destination_route": "", "destination_kwargs": {}}
    path = validate_local_step_path(page_path, "page_path")
    if "*" in page_path:
        raise ValidationError(
            {"page_path": _("Enter an exact page path or leave this field blank.")}
        )

    prefix = get_script_prefix().rstrip("/")
    if prefix and path.startswith(f"{prefix}/"):
        path = path[len(prefix) :]
    try:
        match = resolve(path)
    except Resolver404 as error:
        raise ValidationError({"page_path": _("This page is unavailable.")}) from error
    if match.url_name is None:
        raise ValidationError({"page_path": _("This page has no named route.")})

    return {
        "destination_route": match.view_name,
        "destination_kwargs": {
            name: value if type(value) is int else str(value)
            for name, value in (match.captured_kwargs or {}).items()
        },
    }


def step_page_path(step: TutorialStep, readable: Collection[str]) -> str | None:
    """Reverse the saved route when the caller can read its fields."""
    if not {"destination_route", "destination_kwargs"}.issubset(readable):
        return None
    if not step.destination_route:
        return ""
    try:
        return reverse(step.destination_route, kwargs=step.destination_kwargs)
    except (NoReverseMatch, TypeError, ValueError):
        return None


def validate_step_settings(
    mode: str,
    *,
    interaction: dict[str, Any],
    delay_ms: int = 0,
    url_pattern: str = "",
    hide_next_button: bool = False,
    show_as_tooltip: bool = False,
    include_backdrop: bool = False,
) -> None:
    """Validate the settings and highlight required by the step's presentation."""
    if show_as_tooltip and not interaction["tooltip_highlight_id"]:
        raise ValidationError({"interaction": _("Choose the highlight that anchors the tooltip.")})
    if mode in (
        TutorialStep.AdvanceMode.CLICK,
        TutorialStep.AdvanceMode.DOUBLE_CLICK,
        TutorialStep.AdvanceMode.INPUT,
    ):
        advance_id = interaction["advance_highlight_id"]
        if not advance_id:
            raise ValidationError({"interaction": _("Choose the highlight that advances the step.")})
        if include_backdrop and not any(
            highlight["id"] == advance_id and highlight["allow_interaction"]
            for highlight in interaction["highlights"]
        ):
            raise ValidationError({"interaction": _("Allow interaction on the advance highlight while the backdrop is on.")})
    if mode == TutorialStep.AdvanceMode.DELAY and delay_ms <= 0:
        raise ValidationError({"advance_delay_ms": _("Enter a delay greater than zero.")})
    if hide_next_button and mode == TutorialStep.AdvanceMode.MANUAL:
        raise ValidationError(
            {"hide_next_button": _("Choose an automatic advance condition to hide Next.")}
        )
    if url_pattern:
        if mode != TutorialStep.AdvanceMode.NAVIGATION:
            raise ValidationError(
                {"advance_url_pattern": _("Choose the URL-change advance condition.")}
            )
        validate_local_step_path(url_pattern, "advance_url_pattern")


PREVIEW_FIELDS = frozenset(
    {
        "text",
        "size",
        *STEP_PAGE_FIELDS,
        "include_backdrop",
        "show_as_tooltip",
        "advance_mode",
        "advance_delay_ms",
        "advance_url_pattern",
        "hide_next_button",
        "interaction",
    }
)


def serialize_preview_step(
    step: TutorialStep, field_annotations: dict[str, str] | None
) -> dict[str, Any]:
    """Expose the step's readable presentation fields and sanitize its saved HTML."""
    readable = (
        PREVIEW_FIELDS
        if field_annotations is None
        else {
            field
            for field, annotation in field_annotations.items()
            if getattr(step, annotation, False)
        }
    )
    destination = step_page_path(step, readable)
    if destination and not supports_main_content_navigation(destination):
        destination = None
    advance_mode = (
        step.advance_mode
        if "advance_mode" in readable
        else TutorialStep.AdvanceMode.MANUAL
    )
    if (
        advance_mode == TutorialStep.AdvanceMode.NAVIGATION
        and step.advance_url_pattern
        and "advance_url_pattern" not in readable
    ):
        advance_mode = TutorialStep.AdvanceMode.MANUAL
    if advance_mode == TutorialStep.AdvanceMode.DELAY and (
        "advance_delay_ms" not in readable or step.advance_delay_ms <= 0
    ):
        advance_mode = TutorialStep.AdvanceMode.MANUAL
    return {
        "id": step.pk,
        "name": str(step),
        "text": sanitize_html(step.text, allow_images=True)
        if "text" in readable
        else "",
        "size": step.size if "size" in readable else TutorialStep.Size.SMALL,
        "destination_url": destination,
        "include_backdrop": "include_backdrop" in readable and step.include_backdrop,
        "show_as_tooltip": "show_as_tooltip" in readable and step.show_as_tooltip,
        "advance_mode": advance_mode,
        "advance_delay_ms": step.advance_delay_ms
        if "advance_delay_ms" in readable
        else 0,
        "advance_url_pattern": step.advance_url_pattern
        if advance_mode == TutorialStep.AdvanceMode.NAVIGATION
        else "",
        "hide_next_button": (
            advance_mode != TutorialStep.AdvanceMode.MANUAL
            and "hide_next_button" in readable
            and step.hide_next_button
        ),
        "interaction": step.interaction
        if "interaction" in readable
        else empty_tutorial_step_interaction(),
    }
