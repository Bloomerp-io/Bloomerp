"""Move legacy project labels into the shared attachment catalogue before retirement."""

import json
from copy import deepcopy
from typing import Any, ClassVar
from uuid import UUID

from django.core.exceptions import FieldDoesNotExist
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.operations.base import Operation
from django.db.migrations.state import StateApps
from django.db.models.functions import Lower, Trim


def migrate_todo_labels(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    """Preserve every Todo and Initiative assignment, coalescing normalized label names.

    Existing shared labels keep their names, colors, and ownership. New labels keep
    the legacy owner stamps and use the shared color default. Blank legacy names
    receive a stable UUID-based name so even malformed historical rows survive.
    The copy is idempotent and uses historical models on the migration database.
    """
    database = schema_editor.connection.alias
    legacy_labels = apps.get_model("bloomerp", "TodoLabel").objects.using(database)
    labels = apps.get_model("bloomerp", "Label").objects.using(database)
    assignments = apps.get_model("bloomerp", "ObjectLabel").objects.using(database)
    content_types = apps.get_model("contenttypes", "ContentType").objects.using(
        database
    )
    label_plans: list[tuple[models.Model, str, str]] = []
    targets: dict[UUID, str] = {}
    target_ids: dict[str, int] = {}
    for legacy in legacy_labels.order_by("pk").iterator(chunk_size=1000):
        name = legacy.name.strip() or f"Untitled todo label ({legacy.pk})"
        # Use the database's case conversion, matching Label's unique expression.
        normalized_name = (
            legacy_labels.filter(pk=legacy.pk)
            .annotate(
                normalized_name=Lower(models.Value(name)),
            )
            .values_list("normalized_name", flat=True)
            .get()
        )
        target = f"name:{normalized_name}"
        existing = (
            labels.annotate(normalized_name=Lower(Trim("name")))
            .filter(
                normalized_name=normalized_name,
            )
            .first()
        )
        if existing is not None:
            target_ids[target] = existing.pk
        targets[legacy.pk] = target
        label_plans.append((legacy, name, target))

    # Preflight every affected saved restriction before creating even one label.
    verify_label_row_policies(apps, schema_editor)
    verify_dataview_tile_filters(apps, schema_editor)
    filter_plans = prepare_saved_label_filters(apps, schema_editor, targets, target_ids)
    label_ids: dict[UUID, int] = {}
    for legacy, name, target in label_plans:
        if target not in target_ids:
            target_ids[target] = labels.create(
                name=name,
                created_by_id=legacy.created_by_id,
                updated_by_id=legacy.updated_by_id,
            ).pk
        label_ids[legacy.pk] = target_ids[target]

    for model_name in ("Todo", "Initiative"):
        model = apps.get_model("bloomerp", model_name)
        content_type, _ = content_types.get_or_create(
            app_label="bloomerp",
            model=model_name.lower(),
        )
        legacy_assignments = model._meta.get_field("labels").remote_field.through
        parent_field = f"{model_name.lower()}_id"
        for parent_id, legacy_label_id in (
            legacy_assignments.objects.using(database)
            .values_list(
                parent_field,
                "todolabel_id",
            )
            .iterator(chunk_size=1000)
        ):
            assignments.get_or_create(
                content_type_id=content_type.pk,
                object_id=str(parent_id),
                label_id=label_ids[legacy_label_id],
            )

    saved_filters = apps.get_model("bloomerp", "SavedFilter").objects.using(database)
    for saved_filter_id, groups, positions in filter_plans:
        for group_index, condition_index in positions:
            groups[group_index]["conditions"][condition_index] = (
                translate_label_condition(
                    groups[group_index]["conditions"][condition_index],
                    label_ids,
                )
            )
        saved_filters.filter(pk=saved_filter_id).update(filters=groups)

    retire_label_application_fields(apps, schema_editor)


def historical_filter_model(
    apps: StateApps, content_type: models.Model
) -> type[models.Model] | None:
    """Resolve a filter's model using migration state rather than the runtime registry."""
    try:
        return apps.get_model(content_type.app_label, content_type.model)
    except LookupError:
        return None


def references_legacy_labels(model: type[models.Model] | None, path: str) -> bool:
    """Recognize retired relation paths, including paths through other historical models."""
    for segment in path.replace(".", "__").split("__"):
        if model is None:
            return False
        if (
            model._meta.label_lower in {"bloomerp.todo", "bloomerp.initiative"}
            and segment == "labels"
        ):
            return True
        try:
            field = model._meta.get_field(segment)
        except FieldDoesNotExist:
            return False
        model = field.related_model if field.is_relation else None
    return False


def workspace_references_legacy_labels(
    apps: StateApps,
    database: str,
    workspace_id: str,
    path: str,
) -> bool:
    """Resolve persisted dataview tile/shared aliases before rejecting affected workspace presets."""
    workspaces = apps.get_model("bloomerp", "Workspace").objects.using(database)
    try:
        workspace = workspaces.filter(pk=workspace_id).first()
    except (ValueError, TypeError):
        return False
    seen = set()
    while (
        workspace is not None
        and workspace.source_object_id
        and workspace.pk not in seen
    ):
        seen.add(workspace.pk)
        workspace = workspaces.filter(pk=workspace.source_object_id).first()
    if workspace is None:
        return False
    tile_ids = []
    for row in workspace.layout.get("rows", []):
        for item in row.get("items", []):
            try:
                tile_ids.append(UUID(str(item.get("id"))))
            except (ValueError, TypeError):
                continue
    tiles = (
        apps.get_model("bloomerp", "Tile")
        .objects.using(database)
        .filter(pk__in=tile_ids, type="DATAVIEW_TILE")
    )
    content_types = apps.get_model("contenttypes", "ContentType").objects.using(
        database
    )
    shared_candidates: list[tuple[int, type[models.Model], str]] = []
    for tile in tiles:
        content_type = content_types.filter(
            pk=tile.schema.get("content_type_id")
        ).first()
        model = (
            historical_filter_model(apps, content_type)
            if content_type is not None
            else None
        )
        if path.startswith(f"tile_{tile.pk}:") and references_legacy_labels(
            model, path.split(":", 1)[1]
        ):
            return True
        if model is not None and path.startswith("shared:"):
            shared_path = path[len("shared:") :]
            aliases = tile.schema.get("filter_shared_keys", {})
            for field in model._meta.get_fields():
                alias = aliases.get(field.name, field.name)
                if isinstance(alias, str) and (
                    shared_path == alias or shared_path.startswith(f"{alias}__")
                ):
                    suffix = shared_path[len(alias) :]
                    shared_candidates.append((len(alias), model, field.name + suffix))
    # Shared keys may themselves contain '__'; the live resolver chooses the
    # longest configured key before treating the remainder as a relation path.
    longest = max((length for length, _, _ in shared_candidates), default=0)
    return any(
        length == longest and references_legacy_labels(model, candidate)
        for length, model, candidate in shared_candidates
    )


def verify_dataview_tile_filters(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    """Abort stored initial query filters that would still target a retired relation."""
    database = schema_editor.connection.alias
    content_types = apps.get_model("contenttypes", "ContentType").objects.using(
        database
    )
    for tile in (
        apps.get_model("bloomerp", "Tile")
        .objects.using(database)
        .filter(type="DATAVIEW_TILE")
    ):
        content_type = content_types.filter(
            pk=tile.schema.get("content_type_id")
        ).first()
        model = (
            historical_filter_model(apps, content_type)
            if content_type is not None
            else None
        )
        for key, value in tile.schema.get("initial_query_params", {}).items():
            paths = [
                key[:index] for index, character in enumerate(key) if character == "_"
            ] + [key]
            if key == "filter":
                paths = []
                for payload in value if isinstance(value, list) else [value]:
                    try:
                        groups = json.loads(payload)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(groups, list):
                        paths.extend(
                            condition.get("field_path", "")
                            for group in groups
                            if isinstance(group, dict)
                            for condition in group.get("conditions", [])
                            if isinstance(condition, dict)
                        )
            if any(references_legacy_labels(model, path) for path in paths):
                raise RuntimeError(
                    f"Tile {tile.pk} (initial_query_params.{key}): references retired label fields. "
                    "Review or replace these initial filters before retrying the migration; no tile configuration has changed."
                )


def selected_legacy_label_ids(condition: dict[str, Any]) -> list[UUID]:
    """Normalize only supported membership values, including legacy singleton lists."""
    lookup = condition.get("lookup_id")
    value = condition.get("value")
    if lookup in {"equals", "not_equals"}:
        values = value if isinstance(value, list) else [value]
        if len(values) != 1:
            raise ValueError("single-label comparison requires exactly one UUID")
    elif lookup == "values_in" and isinstance(value, list):
        values = value
    else:
        raise ValueError(
            "only equals, not_equals, and values_in membership lookups can be translated"
        )
    return list(dict.fromkeys(UUID(str(value)) for value in values))


def translate_label_condition(
    condition: dict[str, Any],
    label_ids: dict[UUID, int],
) -> dict[str, Any]:
    """Translate an already preflighted direct condition without changing Boolean structure."""
    translated = deepcopy(condition)
    selected = selected_legacy_label_ids(condition)
    mapped = list(dict.fromkeys(label_ids[legacy_id] for legacy_id in selected))
    translated["field_path"] = "object_labels"
    translated["value"] = mapped if condition["lookup_id"] == "values_in" else mapped[0]
    return translated


def prepare_saved_label_filters(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
    targets: dict[UUID, str],
    target_ids: dict[str, int],
) -> list[tuple[Any, list[dict[str, Any]], list[tuple[int, int]]]]:
    """Plan equivalent direct presets; abort nested, workspace, emptiness, or widened filters."""
    database = schema_editor.connection.alias
    content_types = {
        str(content_type.pk): content_type
        for content_type in apps.get_model("contenttypes", "ContentType")
        .objects.using(database)
        .all()
    }
    plans = []
    assignments = apps.get_model("bloomerp", "ObjectLabel").objects.using(database)
    for saved_filter in (
        apps.get_model("bloomerp", "SavedFilter").objects.using(database).all()
    ):
        content_type = (
            content_types.get(saved_filter.identifier)
            if saved_filter.scope == "model"
            else None
        )
        model = (
            historical_filter_model(apps, content_type)
            if content_type is not None
            else None
        )
        groups = deepcopy(saved_filter.filters)
        positions = []
        for group_index, group in enumerate(groups):
            for condition_index, condition in enumerate(group.get("conditions", [])):
                path = condition.get("field_path", "")
                workspace_label = (
                    saved_filter.scope == "workspace"
                    and workspace_references_legacy_labels(
                        apps,
                        database,
                        saved_filter.identifier,
                        path,
                    )
                )
                if not workspace_label and not references_legacy_labels(model, path):
                    continue
                error = (
                    f"SavedFilter {saved_filter.pk} ({path}): cannot safely migrate legacy labels. "
                    "Review or replace this preset before retrying the migration; no labels or schema have changed. "
                )
                if workspace_label or path != "labels":
                    raise RuntimeError(
                        error
                        + "Nested and workspace label conditions require manual review."
                    )
                try:
                    selected = selected_legacy_label_ids(condition)
                    selected_targets = {targets[legacy_id] for legacy_id in selected}
                except (ValueError, TypeError, KeyError, AttributeError) as exc:
                    raise RuntimeError(error + str(exc)) from exc
                # Compare positive membership sets; equality also proves the
                # complement used by not_equals. Never broaden an existing preset
                # when equal names coalesce or shared labels already have usages.
                through = model._meta.get_field("labels").remote_field.through
                parent_field = f"{model._meta.model_name}_id"
                source = through.objects.using(database)
                before = {
                    str(pk)
                    for pk in source.filter(todolabel_id__in=selected).values_list(
                        parent_field, flat=True
                    )
                }
                coalesced = [
                    legacy_id
                    for legacy_id, target in targets.items()
                    if target in selected_targets
                ]
                after = {
                    str(pk)
                    for pk in source.filter(todolabel_id__in=coalesced).values_list(
                        parent_field, flat=True
                    )
                }
                existing_ids = [
                    target_ids[target]
                    for target in selected_targets
                    if target in target_ids
                ]
                existing_parents = []
                for object_id in assignments.filter(
                    content_type_id=content_type.pk, label_id__in=existing_ids
                ).values_list("object_id", flat=True):
                    try:
                        parent_id = UUID(object_id)
                    except (ValueError, TypeError, AttributeError):
                        continue
                    if str(parent_id) == object_id:
                        existing_parents.append(parent_id)
                after.update(
                    str(pk)
                    for pk in model.objects.using(database)
                    .filter(pk__in=existing_parents)
                    .values_list("pk", flat=True)
                )
                if before != after:
                    raise RuntimeError(
                        error
                        + "Coalescing or existing shared assignments would change matching records."
                    )
                positions.append((group_index, condition_index))
        if positions:
            plans.append((saved_filter.pk, groups, positions))
    return plans


def verify_label_row_policies(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    """Refuse to retire a field used by access rules rather than changing any grant."""
    database = schema_editor.connection.alias
    retired_fields = (
        apps.get_model("bloomerp", "ApplicationField")
        .objects.using(database)
        .filter(
            models.Q(
                content_type__app_label="bloomerp",
                content_type__model__in=("todo", "initiative"),
                field="labels",
            )
            | models.Q(
                content_type__app_label="bloomerp", content_type__model="todolabel"
            ),
        )
    )
    retired_ids = {str(pk) for pk in retired_fields.values_list("pk", flat=True)}
    rules = (
        apps.get_model("bloomerp", "RowPolicyRule")
        .objects.using(database)
        .select_related("row_policy__content_type")
    )
    for rule in rules:
        model = historical_filter_model(apps, rule.row_policy.content_type)
        for condition in rule.rule.get("conditions", []):
            path = str(condition.get("field_path") or condition.get("field") or "")
            operator = condition.get("operator", "")
            paths = (
                [path, operator.lstrip("_")]
                if isinstance(operator, str) and operator.startswith("__")
                else [path]
            )
            if str(condition.get("application_field_id")) in retired_ids or any(
                references_legacy_labels(model, candidate) for candidate in paths
            ):
                raise RuntimeError(
                    f"RowPolicyRule {rule.pk} ({path}): references retired label fields. "
                    "Review and replace this access rule before retrying the migration; no grants have been changed."
                )


def retire_label_application_fields(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    """Remove retired metadata so saved field IDs follow existing missing-field handling."""
    database = schema_editor.connection.alias
    # Normal CLI migration also synchronizes ApplicationField metadata. Retire
    # these rows here so direct Django migrations leave saved layouts/dataviews
    # with missing IDs (which their existing resolution safely ignores), never
    # live metadata pointing at a field or model that no longer exists.
    apps.get_model("bloomerp", "ApplicationField").objects.using(database).filter(
        models.Q(
            content_type__app_label="bloomerp",
            content_type__model__in=("todo", "initiative"),
            field="labels",
        )
        | models.Q(
            content_type__app_label="bloomerp",
            content_type__model="todolabel",
        ),
    ).delete()


class Migration(migrations.Migration):
    """Copy both legacy relationships before irreversibly dropping their schema."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("bloomerp", "0092_conversation_activity"),
    ]
    operations: ClassVar[list[Operation]] = [
        migrations.RunPython(migrate_todo_labels),
        migrations.RemoveField(model_name="todo", name="labels"),
        migrations.RemoveField(model_name="initiative", name="labels"),
        migrations.DeleteModel(name="TodoLabel"),
    ]
