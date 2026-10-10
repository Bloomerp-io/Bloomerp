"""Create tagging and file-reference tables, then copy legacy files and usages.

Legacy folders are not copied: migrated files have no physical parent. Storage
keys and legacy rows remain unchanged. Stop legacy file writers during this
snapshot migration. Reversing drops the new tables; the legacy source remains.
"""

from __future__ import annotations

import mimetypes
import uuid
import warnings
from pathlib import PurePosixPath
from typing import Any, ClassVar
from uuid import UUID, uuid5

import django.db.models.deletion
import django.db.models.functions.text
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import migrations, models, transaction
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

import bloomerp.model_fields.user_field
import bloomerp.models.files.file_node
from bloomerp.files.definition import FileNodeMetaData

REFERENCE_NAMESPACE = UUID("10feebac-7c39-54a8-b6eb-302fa0d615b6")


def copy_stamps(source: models.Model) -> dict[str, Any]:
    """Carry original timestamps and user identities into the additive copy."""
    return {
        "datetime_created": source.datetime_created,
        "datetime_updated": source.datetime_updated,
        "created_by_id": source.created_by_id,
        "updated_by_id": source.updated_by_id,
    }


def ensure_node(
    node_model: type[models.Model], database: str, node_id: UUID, values: dict[str, Any]
) -> None:
    """Insert one node or reject an existing identity with conflicting source data."""
    nodes = node_model.objects.using(database)
    existing = nodes.filter(pk=node_id).values(*values).first()
    if existing is not None:
        if existing != values:
            raise RuntimeError(
                f"File migration conflict for node {node_id}; no existing node was overwritten."
            )
        return
    node = nodes.create(pk=node_id, **values)
    # auto_now/auto_now_add override values on insert, even on historical models.
    nodes.filter(pk=node.pk).update(
        datetime_created=values["datetime_created"],
        datetime_updated=values["datetime_updated"],
    )


def canonical_target(
    apps: StateApps, database: str, content_type: models.Model, object_id: Any
) -> str:
    """Resolve a recorded target without guessing associations for missing records."""
    try:
        target_model = apps.get_model(content_type.app_label, content_type.model)
        identity = target_model._meta.pk.to_python(object_id)
        exists = target_model.objects.using(database).filter(pk=identity).exists()
    except (LookupError, ValidationError, ValueError, TypeError) as error:
        raise RuntimeError(
            f"Cannot resolve legacy file target {content_type.app_label}.{content_type.model}:{object_id}."
        ) from error
    if not exists:
        raise RuntimeError(
            f"Missing legacy file target {content_type.app_label}.{content_type.model}:{object_id}."
        )
    return str(identity)


def ensure_reference(
    reference_model: type[models.Model],
    database: str,
    file: models.Model,
    content_type_id: int,
    object_id: str,
    application_field_id: int | None = None,
    occurrence_id: UUID | None = None,
) -> None:
    """Deduplicate identical usages while retaining field and placement distinctions."""
    identity = {
        "file_id": file.pk,
        "content_type_id": content_type_id,
        "object_id": object_id,
        "application_field_id": application_field_id,
        "occurrence_id": occurrence_id,
    }
    references = reference_model.objects.using(database)
    if references.filter(**identity).exists():
        return
    key = repr(
        (
            str(file.pk),
            content_type_id,
            object_id,
            application_field_id,
            str(occurrence_id),
        )
    )
    reference = references.create(
        pk=uuid5(REFERENCE_NAMESPACE, key), **identity, **copy_stamps(file)
    )
    references.filter(pk=reference.pk).update(
        datetime_created=file.datetime_created, datetime_updated=file.datetime_updated
    )


def file_metadata(file: models.Model) -> tuple[dict[str, Any], bool]:
    """Cache storage size once and preserve all source metadata for reconciliation."""
    if not file.file.name:
        raise RuntimeError(f"Legacy file {file.pk} has no storage key.")
    filename = PurePosixPath(file.file.name).name
    mime_type, encoding = mimetypes.guess_type(filename)
    missing = False
    try:
        size = file.file.size
    except FileNotFoundError:
        size = None
        missing = True
    metadata = FileNodeMetaData(
        size=size,
        original_filename=filename,
        extension=PurePosixPath(filename).suffix.lstrip(".").lower(),
        mime_type=mime_type or "application/octet-stream",
        content_encoding=encoding,
        legacy_file={
            "id": str(file.pk),
            "persisted": file.persisted,
            "folder_id": file.folder_id,
            "meta": file.meta,
            "content_type_id": file.content_type_id,
            "object_id": file.object_id,
        },
    )
    return metadata.model_dump(mode="json", exclude_none=True), missing


def template_ids(meta: Any) -> set[UUID]:
    """Read both historical flat and current nested document-template provenance."""
    if meta is None:
        return set()
    if not isinstance(meta, dict):
        raise TypeError(
            "Legacy file metadata must be a JSON object to resolve document templates."
        )
    values = [meta.get("document_template_id")]
    template = meta.get("document_template")
    values.append(template.get("id") if isinstance(template, dict) else template)
    try:
        return {UUID(str(value)) for value in values if value is not None}
    except (ValueError, TypeError) as error:
        raise RuntimeError(
            "Invalid document-template ID in legacy file metadata."
        ) from error


def migrate_files(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Atomically copy all legacy files and their recorded object/template usages."""
    database = schema_editor.connection.alias
    file_model = apps.get_model("bloomerp", "File")
    node_model = apps.get_model("bloomerp", "FileNode")
    reference_model = apps.get_model("bloomerp", "FileReference")
    field_reference_model = apps.get_model("bloomerp", "FileFieldReference")
    content_type_model = apps.get_model("contenttypes", "ContentType")
    missing_files = 0
    with transaction.atomic(using=database):
        # Avoid creating ContentTypes for empty installations during initial migration.
        template_type = None
        files = (
            file_model.objects.using(database)
            .select_related("content_type")
            .order_by("pk")
        )
        for file in files.iterator(chunk_size=500):
            metadata, missing = file_metadata(file)
            missing_files += int(missing)
            ensure_node(
                node_model,
                database,
                file.pk,
                {
                    "name": file.name or PurePosixPath(file.file.name).name,
                    "kind": "FILE",
                    "content": file.file.name,
                    "parent_id": None,
                    "meta": metadata,
                    **copy_stamps(file),
                },
            )
            if file.object_id:
                if file.content_type_id is None:
                    raise RuntimeError(
                        f"Legacy file {file.pk} has an object ID but no content type."
                    )
                target_id = canonical_target(
                    apps, database, file.content_type, file.object_id
                )
                ensure_reference(
                    reference_model, database, file, file.content_type_id, target_id
                )
            references = (
                field_reference_model.objects.using(database)
                .filter(file_id=file.pk)
                .select_related("application_field__content_type")
            )
            for reference in references.iterator(chunk_size=500):
                field = reference.application_field
                target_id = canonical_target(
                    apps, database, field.content_type, reference.object_id
                )
                ensure_reference(
                    reference_model,
                    database,
                    file,
                    field.content_type_id,
                    target_id,
                    field.pk,
                    reference.occurrence_id,
                )
            for template_id in template_ids(file.meta):
                if template_type is None:
                    template_type, _ = content_type_model.objects.using(
                        database
                    ).get_or_create(app_label="bloomerp", model="documenttemplate")
                target_id = canonical_target(apps, database, template_type, template_id)
                ensure_reference(
                    reference_model, database, file, template_type.pk, target_id
                )
        copied = (
            node_model.objects.using(database)
            .filter(pk__in=files.values("pk"), kind="FILE")
            .count()
        )
        if copied != files.count():
            raise RuntimeError("Legacy file/node count reconciliation failed.")
    if missing_files:
        warnings.warn(
            f"File migration preserved {missing_files} unavailable storage keys with unknown size; restore their content before cutover.",
            RuntimeWarning,
            stacklevel=2,
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("bloomerp", "0085_emailaccount_mailbox_mapping"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations: ClassVar[list[migrations.operations.base.Operation]] = [
        migrations.CreateModel(
            name="FileNode",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "datetime_created",
                    models.DateTimeField(
                        auto_now_add=True, verbose_name="Datetime Created"
                    ),
                ),
                (
                    "datetime_updated",
                    models.DateTimeField(
                        auto_now=True, verbose_name="Datetime Updated"
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "kind",
                    models.CharField(
                        choices=[("FILE", "File"), ("FOLDER", "Folder")], max_length=9
                    ),
                ),
                (
                    "content",
                    models.FileField(
                        blank=True,
                        max_length=255,
                        null=True,
                        upload_to=bloomerp.models.files.file_node.file_node_upload_to,
                    ),
                ),
                ("meta", models.JSONField(blank=True, default=dict)),
            ],
            options={
                "db_table": "bloomerp_file_node",
                "default_permissions": (
                    "add",
                    "change",
                    "delete",
                    "view",
                    "export",
                    "import",
                    "bulk_add",
                    "bulk_change",
                    "bulk_delete",
                ),
            },
        ),
        migrations.CreateModel(
            name="FileReference",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "datetime_created",
                    models.DateTimeField(
                        auto_now_add=True, verbose_name="Datetime Created"
                    ),
                ),
                (
                    "datetime_updated",
                    models.DateTimeField(
                        auto_now=True, verbose_name="Datetime Updated"
                    ),
                ),
                ("object_id", models.CharField(max_length=100)),
                ("occurrence_id", models.UUIDField(blank=True, null=True)),
            ],
            options={
                "db_table": "bloomerp_file_reference",
                "default_permissions": (
                    "add",
                    "change",
                    "delete",
                    "view",
                    "export",
                    "import",
                    "bulk_add",
                    "bulk_change",
                    "bulk_delete",
                ),
            },
        ),
        migrations.CreateModel(
            name="Label",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                ("color", models.CharField(default="#64748b", max_length=7)),
            ],
        ),
        migrations.CreateModel(
            name="Mention",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("object_id", models.CharField(max_length=255)),
                ("occurrence_id", models.UUIDField(blank=True, null=True)),
            ],
            options={
                "db_table": "bloomerp_mention",
            },
        ),
        migrations.CreateModel(
            name="ObjectLabel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("object_id", models.CharField(max_length=255)),
            ],
        ),
        migrations.CreateModel(
            name="Tag",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("source_object_id", models.CharField(max_length=255)),
                ("target_object_id", models.CharField(max_length=255)),
                ("occurrence_id", models.UUIDField(blank=True, null=True)),
            ],
        ),
        migrations.AddField(
            model_name="filefieldreference",
            name="occurrence_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="filefieldreference",
            name="file",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="field_references",
                related_query_name="field_reference",
                to="bloomerp.file",
            ),
        ),
        migrations.AddConstraint(
            model_name="filefieldreference",
            constraint=models.UniqueConstraint(
                condition=models.Q(("occurrence_id__isnull", True)),
                fields=("file", "application_field", "object_id"),
                name="file_field_assignment_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="filefieldreference",
            constraint=models.UniqueConstraint(
                condition=models.Q(("occurrence_id__isnull", False)),
                fields=("application_field", "object_id", "occurrence_id"),
                name="file_inline_occurrence_unique",
            ),
        ),
        migrations.AddField(
            model_name="filenode",
            name="created_by",
            field=bloomerp.model_fields.user_field.UserField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="%(class)s_created",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Created By",
            ),
        ),
        migrations.AddField(
            model_name="filenode",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="children",
                to="bloomerp.filenode",
            ),
        ),
        migrations.AddField(
            model_name="filenode",
            name="updated_by",
            field=bloomerp.model_fields.user_field.UserField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="%(class)s_updated",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Updated By",
            ),
        ),
        migrations.AddField(
            model_name="filereference",
            name="application_field",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="bloomerp.applicationfield",
            ),
        ),
        migrations.AddField(
            model_name="filereference",
            name="content_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="contenttypes.contenttype",
            ),
        ),
        migrations.AddField(
            model_name="filereference",
            name="created_by",
            field=bloomerp.model_fields.user_field.UserField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="%(class)s_created",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Created By",
            ),
        ),
        migrations.AddField(
            model_name="filereference",
            name="file",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="references",
                to="bloomerp.filenode",
            ),
        ),
        migrations.AddField(
            model_name="filereference",
            name="updated_by",
            field=bloomerp.model_fields.user_field.UserField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="%(class)s_updated",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Updated By",
            ),
        ),
        migrations.AddField(
            model_name="label",
            name="created_by",
            field=bloomerp.model_fields.user_field.UserField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="%(class)s_created",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Created By",
            ),
        ),
        migrations.AddField(
            model_name="label",
            name="updated_by",
            field=bloomerp.model_fields.user_field.UserField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="%(class)s_updated",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Updated By",
            ),
        ),
        migrations.AddField(
            model_name="mention",
            name="application_field",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="bloomerp.applicationfield",
            ),
        ),
        migrations.AddField(
            model_name="mention",
            name="content_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="contenttypes.contenttype",
            ),
        ),
        migrations.AddField(
            model_name="mention",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL
            ),
        ),
        migrations.AddField(
            model_name="objectlabel",
            name="content_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="contenttypes.contenttype",
            ),
        ),
        migrations.AddField(
            model_name="objectlabel",
            name="label",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, to="bloomerp.label"
            ),
        ),
        migrations.AddField(
            model_name="tag",
            name="application_field",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="bloomerp.applicationfield",
            ),
        ),
        migrations.AddField(
            model_name="tag",
            name="source_content_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="source_tags",
                to="contenttypes.contenttype",
            ),
        ),
        migrations.AddField(
            model_name="tag",
            name="target_content_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="target_tags",
                to="contenttypes.contenttype",
            ),
        ),
        migrations.AddConstraint(
            model_name="filenode",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("content__isnull", False),
                        ("kind", "FILE"),
                        models.Q(("content", ""), _negated=True),
                    ),
                    models.Q(
                        ("kind", "FOLDER"),
                        models.Q(
                            ("content__isnull", True), ("content", ""), _connector="OR"
                        ),
                    ),
                    _connector="OR",
                ),
                name="file_node_kind_content_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="filenode",
            constraint=models.CheckConstraint(
                condition=models.Q(("parent", models.F("pk")), _negated=True),
                name="file_node_not_own_parent",
            ),
        ),
        migrations.AddIndex(
            model_name="filereference",
            index=models.Index(
                fields=["content_type", "object_id", "application_field"],
                name="file_ref_record_field_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="filereference",
            index=models.Index(
                fields=["occurrence_id"], name="file_ref_occurrence_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="filereference",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("occurrence_id__isnull", True),
                    ("application_field__isnull", False),
                    _connector="OR",
                ),
                name="file_ref_occurrence_has_field",
            ),
        ),
        migrations.AddConstraint(
            model_name="filereference",
            constraint=models.CheckConstraint(
                condition=models.Q(("object_id", ""), _negated=True),
                name="file_ref_object_id_not_empty",
            ),
        ),
        migrations.AddConstraint(
            model_name="filereference",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("application_field__isnull", True), ("occurrence_id__isnull", True)
                ),
                fields=("file", "content_type", "object_id"),
                name="file_ref_record_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="filereference",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("application_field__isnull", False),
                    ("occurrence_id__isnull", True),
                ),
                fields=("file", "content_type", "object_id", "application_field"),
                name="file_ref_field_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="filereference",
            constraint=models.UniqueConstraint(
                condition=models.Q(("occurrence_id__isnull", False)),
                fields=(
                    "content_type",
                    "object_id",
                    "application_field",
                    "occurrence_id",
                ),
                name="file_ref_occurrence_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="label",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower(
                    django.db.models.functions.text.Trim("name")
                ),
                name="label_name_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="mention",
            index=models.Index(
                fields=["content_type", "object_id"],
                name="bloomerp_me_content_71355a_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="mention",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("application_field__isnull", True),
                        ("occurrence_id__isnull", True),
                    ),
                    models.Q(
                        ("application_field__isnull", False),
                        ("occurrence_id__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="mention_inline_pair",
            ),
        ),
        migrations.AddConstraint(
            model_name="mention",
            constraint=models.UniqueConstraint(
                condition=models.Q(("application_field__isnull", True)),
                fields=("content_type", "object_id", "user"),
                name="mention_manual_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="mention",
            constraint=models.UniqueConstraint(
                condition=models.Q(("application_field__isnull", False)),
                fields=(
                    "content_type",
                    "object_id",
                    "application_field",
                    "occurrence_id",
                ),
                name="mention_occurrence_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="objectlabel",
            constraint=models.UniqueConstraint(
                fields=("content_type", "object_id", "label"),
                name="object_label_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="tag",
            index=models.Index(
                fields=["source_content_type", "source_object_id"],
                name="bloomerp_ta_source__a92e7a_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="tag",
            index=models.Index(
                fields=["target_content_type", "target_object_id"],
                name="bloomerp_ta_target__b1fa26_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="tag",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("application_field__isnull", True),
                        ("occurrence_id__isnull", True),
                    ),
                    models.Q(
                        ("application_field__isnull", False),
                        ("occurrence_id__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="tag_inline_pair",
            ),
        ),
        migrations.AddConstraint(
            model_name="tag",
            constraint=models.UniqueConstraint(
                condition=models.Q(("application_field__isnull", True)),
                fields=(
                    "source_content_type",
                    "source_object_id",
                    "target_content_type",
                    "target_object_id",
                ),
                name="tag_manual_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="tag",
            constraint=models.UniqueConstraint(
                condition=models.Q(("application_field__isnull", False)),
                fields=(
                    "source_content_type",
                    "source_object_id",
                    "application_field",
                    "occurrence_id",
                ),
                name="tag_occurrence_unique",
            ),
        ),
        migrations.RunPython(migrate_files, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="aiartifact", name="file",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.RESTRICT, related_name="ai_artifacts", to="bloomerp.filenode"),
        ),
        migrations.AlterField(
            model_name="fileextraction", name="source_file",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to="bloomerp.filenode", verbose_name="Source File"),
        ),
    ]
