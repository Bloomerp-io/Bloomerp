"""Install stable tutorial defaults from the tutorials directory of each app."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

import yaml
from django.apps import AppConfig, apps
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from django.db import DatabaseError, models, transaction
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints
from pydantic import ValidationError as SchemaError
from rest_framework.exceptions import ValidationError as SerializerError
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from bloomerp.models.tutorial import (
    Tutorial,
    TutorialRevision,
    TutorialStep,
    TutorialTopic,
)
from bloomerp.models.tutorial.tutorial import (
    REVISION_EXPORT_FIELDS,
    STEP_EXPORT_FIELDS,
    TUTORIAL_YAML_VERSION,
    validate_tutorial_user_filter,
)
from bloomerp.models.tutorial.tutorial_step import empty_tutorial_step_interaction
from bloomerp.serializers.tutorial_step import (
    TutorialStepFieldsSerializer,
    validate_local_step_path,
    validate_step_settings,
)
from bloomerp.utils.rich_text import sanitize_html

_SOURCE_SLUG = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
_APP_NAME = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", re.ASCII)
_Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
_Sequence = Annotated[int, Field(ge=0, le=2_147_483_647)]


class TutorialYamlLoader(yaml.SafeLoader):
    """Read safe YAML without silently replacing repeated mapping keys."""

    def construct_mapping(
        self, node: MappingNode, deep: bool = False
    ) -> dict[Any, Any]:
        """Reject duplicate keys, including duplicates inside steps and filters."""
        mapping = super().construct_mapping(node, deep=deep)
        if len(mapping) != len(node.value):
            raise ConstructorError(
                None, None, "Duplicate YAML mapping key", node.start_mark
            )
        return mapping


class TutorialSchema(BaseModel):
    """Share strict field and type checking across YAML definitions."""

    model_config = ConfigDict(extra="forbid", strict=True)


class StepDefinition(TutorialSchema):
    """Store the portable step content and its identity within a revision."""

    sequence: _Sequence
    key: str
    name: _Name
    text: str = ""
    size: str = "small"
    destination_route: str = ""
    destination_kwargs: dict[str, str | int] = Field(default_factory=dict)
    interaction: dict[str, JsonValue] = Field(
        default_factory=empty_tutorial_step_interaction
    )
    show_as_tooltip: bool = False
    include_backdrop: bool = True
    advance_mode: str = "manual"
    advance_delay_ms: _Sequence = 0
    advance_url_pattern: str = ""
    hide_next_button: bool = False
    is_optional: bool = False


class RevisionDefinition(TutorialSchema):
    """Keep publish state and ordered steps together as a revision snapshot."""

    number: Annotated[_Sequence, Field(ge=1)]
    trigger_route: Annotated[str, StringConstraints(max_length=255)] = ""
    auto_start: bool = False
    published_at: datetime | str | None = None
    steps: list[StepDefinition]

    def publication_time(self) -> datetime | None:
        """Read the exported ISO publication timestamp with an explicit timezone."""
        timestamp = self.published_at
        if timestamp is None:
            return None
        if isinstance(timestamp, str):
            timestamp = parse_datetime(timestamp)
        if timestamp is None or not is_aware(timestamp):
            raise ValueError(
                "published_at must be an ISO timestamp with a timezone or null."
            )
        return timestamp


class TutorialDefinition(TutorialSchema):
    """Describe one portable tutorial and its audience defaults."""

    source_key: str
    name: _Name
    description: str = ""
    is_active: bool = True
    available_to_all: bool = False
    user_filter: list[dict[str, JsonValue]] = Field(default_factory=list)
    topics: list[str] | None = None
    revisions: list[RevisionDefinition]


class TopicDefinition(TutorialSchema):
    """Describe a reusable topic and its catalog order."""

    source_key: str
    name: _Name
    description: str = ""
    sequence: _Sequence = 0


class TutorialDocument(TutorialSchema):
    """Validate the structure used by an ordinary tutorial export."""

    schema_version: int
    tutorial: TutorialDefinition


class TopicDocument(TutorialSchema):
    """Read a manifest of shared topics."""

    schema_version: int
    topics: list[TopicDefinition]


class RetirementDocument(TutorialSchema):
    """Mark a tutorial key as retired without rewriting its revisions."""

    schema_version: int
    retire: str


@dataclass
class TutorialDefaults:
    """Keep each validated declaration paired with its source file for diagnostics."""

    tutorials: dict[str, tuple[str, TutorialDefinition]]
    topics: dict[str, tuple[str, TopicDefinition]]
    retirements: dict[str, str]


@dataclass(frozen=True)
class TutorialSyncResult:
    """Report the declarations processed by one successful synchronization."""

    tutorials: int
    topics: int
    retired: int


def qualified_key(app_name: str, key: str, *, reference: bool = False) -> str:
    """Scope a slug to its app and prevent definitions from claiming another namespace."""
    namespace, separator, slug = key.partition(":")
    if not separator:
        namespace, slug = app_name, namespace
    scoped = f"{namespace}:{slug}"
    if (
        (namespace != app_name and not reference)
        or not _APP_NAME.fullmatch(namespace)
        or not _SOURCE_SLUG.fullmatch(slug)
        or len(scoped) > 255
    ):
        raise ValueError(
            f"Invalid source key {key!r}. Use a stable slug scoped to the owning app."
        )
    return scoped


def validate_tutorial_definition(definition: TutorialDefinition) -> None:
    """Validate audience filters and the same presentation rules used by the editor."""
    validate_tutorial_user_filter(definition.user_filter)
    definition.description = sanitize_html(definition.description, allow_images=True)
    seen_numbers = set()
    for revision in definition.revisions:
        if revision.number in seen_numbers:
            raise ValueError(f"Duplicate revision number {revision.number}.")
        seen_numbers.add(revision.number)
        try:
            revision.published_at = revision.publication_time()
            if revision.published_at and not revision.steps:
                raise ValueError("A published revision must contain at least one step.")
            if revision.auto_start and not revision.trigger_route:
                raise ValueError("Auto-start requires a trigger route.")
            if revision.trigger_route.startswith("/"):
                validate_local_step_path(revision.trigger_route, "trigger_route")
            elif revision.trigger_route and not re.fullmatch(
                r"[\w.:-]+", revision.trigger_route
            ):
                raise ValueError(
                    "Use a Django route name or local path as the trigger."
                )
            sequences = set()
            keys = set()
            for step in revision.steps:
                if step.sequence in sequences or step.key in keys:
                    raise ValueError(
                        f"Duplicate step sequence or key: {step.sequence}, {step.key!r}."
                    )
                sequences.add(step.sequence)
                keys.add(step.key)
                candidate = TutorialStep(**step.model_dump())
                candidate.full_clean(
                    exclude={"revision"},
                    validate_unique=False,
                    validate_constraints=False,
                )
                serializer = TutorialStepFieldsSerializer(data=step.model_dump())
                serializer.is_valid(raise_exception=True)
                step.interaction = serializer.validated_data["interaction"]
                step.text = serializer.validated_data["text"]
                validate_step_settings(
                    step.advance_mode,
                    interaction=step.interaction,
                    delay_ms=step.advance_delay_ms,
                    url_pattern=step.advance_url_pattern,
                    show_as_tooltip=step.show_as_tooltip,
                    hide_next_button=step.hide_next_button,
                    include_backdrop=step.include_backdrop,
                )
        except (ValueError, ValidationError, SerializerError) as error:
            raise ValueError(f"Revision {revision.number}: {error}") from error
        revision.steps.sort(key=step_sequence)


def step_sequence(step: StepDefinition) -> int:
    """Return the persisted presentation order for comparison and insertion."""
    return step.sequence


def read_tutorial_defaults(app_configs: list[AppConfig]) -> TutorialDefaults:
    """Discover and validate all installed definitions before writing any records."""
    defaults = TutorialDefaults(tutorials={}, topics={}, retirements={})
    for app in app_configs:
        from pathlib import Path

        directory = Path(app.path) / "tutorials"
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix not in {".yaml", ".yml"}:
                continue
            source = f"{app.name}/{path.relative_to(app.path).as_posix()}"
            try:
                document = yaml.load(
                    path.read_text(encoding="utf-8"), Loader=TutorialYamlLoader
                )
                if (
                    not isinstance(document, dict)
                    or type(document.get("schema_version")) is not int
                ):
                    raise ValueError(
                        "A mapping with an integer schema_version is required."
                    )
                if document["schema_version"] != TUTORIAL_YAML_VERSION:
                    raise ValueError(
                        f"Unsupported tutorial schema version {document['schema_version']}."
                    )
                if "topics" in document:
                    for topic in TopicDocument.model_validate(document).topics:
                        key = qualified_key(app.name, topic.source_key)
                        if key in defaults.topics:
                            raise ValueError(
                                f"Duplicate topic key {key!r}; also declared in {defaults.topics[key][0]}."
                            )
                        defaults.topics[key] = (source, topic)
                    continue

                if "retire" in document:
                    definition = None
                    raw_key = RetirementDocument.model_validate(document).retire
                else:
                    definition = TutorialDocument.model_validate(document).tutorial
                    raw_key = definition.source_key
                key = qualified_key(app.name, raw_key)
                if key in defaults.retirements or key in defaults.tutorials:
                    original = (
                        defaults.retirements.get(key) or defaults.tutorials[key][0]
                    )
                    raise ValueError(
                        f"Duplicate or conflicting tutorial key {key!r}; also declared in {original}."
                    )
                if definition is None:
                    defaults.retirements[key] = source
                    continue
                if definition.topics is not None:
                    definition.topics = [
                        qualified_key(app.name, topic, reference=True)
                        for topic in definition.topics
                    ]
                    if len(set(definition.topics)) != len(definition.topics):
                        raise ValueError(
                            "A tutorial may reference each topic only once."
                        )
                validate_tutorial_definition(definition)
                defaults.tutorials[key] = (source, definition)
            except (
                OSError,
                ValueError,
                SchemaError,
                ValidationError,
                yaml.YAMLError,
            ) as error:
                raise CommandError(f"{source}: {error}") from error

    for source, definition in defaults.tutorials.values():
        for key in definition.topics or ():
            if key not in defaults.topics:
                raise CommandError(f"{source}: Unknown tutorial topic {key!r}.")
    return defaults


def validate_existing_revision(
    source: str,
    existing: TutorialRevision,
    definition: RevisionDefinition,
) -> None:
    """Reject a collided revision before saving any defaults."""
    for field in REVISION_EXPORT_FIELDS:
        if field != "published_at" and getattr(existing, field) != getattr(
            definition, field
        ):
            break
    else:
        if not (existing.published_at and definition.published_at is None):
            current_steps = list(
                existing.steps.order_by("sequence").values(*STEP_EXPORT_FIELDS)
            )
            if current_steps == [step.model_dump() for step in definition.steps]:
                return
    raise CommandError(
        f"{source}: Revision {definition.number} conflicts with the saved revision. "
        "Use a new revision number for changed content."
    )


def update_default_record(record: models.Model, values: dict[str, Any]) -> None:
    """Save only changed source fields so unchanged runs leave timestamps intact."""
    fields = [
        field for field, value in values.items() if getattr(record, field) != value
    ]
    if fields:
        for field in fields:
            setattr(record, field, values[field])
        record.save(update_fields=[*fields, "datetime_updated"])


@transaction.atomic
def apply_tutorial_defaults(defaults: TutorialDefaults) -> TutorialSyncResult:
    """Lock existing source records, preflight collisions, and apply one atomic sync."""
    existing_tutorials = {
        tutorial.source_key: tutorial
        for tutorial in Tutorial.objects.select_for_update()
        .filter(source_key__in=defaults.tutorials.keys() | defaults.retirements.keys())
        .order_by("pk")
    }
    existing_revisions = {
        (revision.tutorial_id, revision.number): revision
        for revision in TutorialRevision.objects.select_for_update()
        .filter(tutorial__in=existing_tutorials.values())
        .order_by("pk")
    }
    for key, (source, definition) in defaults.tutorials.items():
        tutorial = existing_tutorials.get(key)
        if tutorial is not None:
            for revision in definition.revisions:
                existing = existing_revisions.get((tutorial.pk, revision.number))
                if existing is not None:
                    validate_existing_revision(source, existing, revision)

    topics = {
        topic.source_key: topic
        for topic in TutorialTopic.objects.select_for_update()
        .filter(source_key__in=defaults.topics)
        .order_by("pk")
    }
    for key, (source, topic) in defaults.topics.items():
        values = topic.model_dump(exclude={"source_key"})
        try:
            if key in topics:
                update_default_record(topics[key], values)
            else:
                topics[key] = TutorialTopic.objects.create(source_key=key, **values)
        except DatabaseError as error:
            raise CommandError(
                f"{source}: Could not synchronize topic {key!r}: {error}"
            ) from error

    for key, (source, definition) in defaults.tutorials.items():
        try:
            tutorial = existing_tutorials.get(key)
            if tutorial is None:
                tutorial = Tutorial.objects.create(
                    source_key=key,
                    **definition.model_dump(
                        exclude={"source_key", "topics", "revisions"}
                    ),
                )
            else:
                update_default_record(
                    tutorial,
                    {
                        "name": definition.name,
                        "description": definition.description,
                        "source_retired": False,
                    },
                )

            if definition.topics is not None:
                local_topics = tutorial.topics.filter(
                    models.Q(source_key__isnull=True) | models.Q(source_key="")
                )
                tutorial.topics.set(
                    [*local_topics, *(topics[key] for key in definition.topics)]
                )

            for revision in definition.revisions:
                existing = existing_revisions.get((tutorial.pk, revision.number))
                if existing is not None:
                    if (
                        existing.published_at is None
                        and revision.published_at is not None
                    ):
                        update_default_record(
                            existing, {"published_at": revision.published_at}
                        )
                    continue
                saved = TutorialRevision.objects.create(
                    tutorial=tutorial,
                    **revision.model_dump(exclude={"steps"}),
                )
                TutorialStep.objects.bulk_create(
                    [
                        TutorialStep(revision=saved, **step.model_dump())
                        for step in revision.steps
                    ]
                )
        except DatabaseError as error:
            raise CommandError(
                f"{source}: Could not synchronize tutorial {key!r}: {error}"
            ) from error

    retired = 0
    for key, source in defaults.retirements.items():
        tutorial = existing_tutorials.get(key)
        if tutorial is not None:
            try:
                update_default_record(tutorial, {"source_retired": True})
            except DatabaseError as error:
                raise CommandError(
                    f"{source}: Could not retire tutorial {key!r}: {error}"
                ) from error
            retired += 1
    return TutorialSyncResult(len(defaults.tutorials), len(defaults.topics), retired)


def sync_default_tutorials() -> TutorialSyncResult:
    """Synchronize YAML defaults for the Django apps installed in this project."""
    defaults = read_tutorial_defaults(list(apps.get_app_configs()))
    if not any((defaults.tutorials, defaults.topics, defaults.retirements)):
        return TutorialSyncResult(0, 0, 0)
    try:
        return apply_tutorial_defaults(defaults)
    except DatabaseError as error:
        raise CommandError(
            f"Could not synchronize tutorials. Run migrations first. {error}"
        ) from error
